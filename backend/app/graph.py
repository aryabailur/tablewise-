"""LangGraph concierge: router -> retrieve -> booking_agent <-> tools -> respond (+ guardrail for off-topic).

Multi-restaurant: the graph state carries `current_restaurant` (persisted per thread by the checkpointer). It is set
from ChatRequest.restaurant_slug, when the guest names a restaurant, or when a tool is called for one. The
"discover" intent lets the agent search restaurants and emits a `restaurants` UI event with the matches.
Streams UI events (node transitions, tokens, tool calls, sources, bookings, restaurants) via `run_chat`.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time as _time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import InjectedState, ToolNode
from pydantic import BaseModel, Field

from . import allergens, metrics, rag
from . import booking_service as bs
from .seed import RESTAURANTS as _SEED_RESTAURANTS

_BACKEND = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND / ".env")
load_dotenv(_BACKEND.parent / ".env")

PROVIDER = (os.getenv("LLM_PROVIDER") or ("groq" if os.getenv("GROQ_API_KEY") else "anthropic")).lower()
_DEFAULT_MODELS = {"groq": "openai/gpt-oss-120b", "anthropic": "claude-sonnet-4-5"}
MODEL = os.getenv("LLM_MODEL") or _DEFAULT_MODELS.get(PROVIDER, "openai/gpt-oss-120b")
LLM_ENABLED = bool(os.getenv("GROQ_API_KEY") if PROVIDER == "groq" else os.getenv("ANTHROPIC_API_KEY"))
INTENTS = ("info", "booking", "discover", "smalltalk", "offtopic")


def _llm(max_tokens: int = 1500):
    if PROVIDER == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=MODEL, max_tokens=max_tokens, max_retries=2, temperature=0.3)
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=MODEL, max_tokens=max_tokens, max_retries=2)


# ====================================================================== restaurant resolution

def _aliases() -> dict[str, str]:
    """alias (lowercase) -> slug. Static (from the seed list) so routing never needs the database."""
    out: dict[str, str] = {}
    for r in _SEED_RESTAURANTS:
        slug, name = r["slug"], r["name"].lower()
        for a in {slug, slug.replace("-", " "), name, name.replace("&", "and"), name.replace(" & ", " "),
                  slug.split("-")[0]}:
            out[a] = slug
    out["alba"] = "trattoria-alba"
    return out


_ALIASES = _aliases()
_ALIAS_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _ALIASES), key=len, reverse=True)) + r")\b")
_SLUGS = tuple(r["slug"] for r in _SEED_RESTAURANTS)


def resolve_restaurant(value: str | None) -> str | None:
    """Map a slug or restaurant name ("Trattoria Alba", "alba") to its slug."""
    if not value:
        return None
    v = value.strip().lower()
    if v in _ALIASES:
        return _ALIASES[v]
    m = _ALIAS_RE.search(v)
    return _ALIASES[m.group(1)] if m else None


def mentioned_restaurants(text: str) -> list[str]:
    seen: list[str] = []
    for m in _ALIAS_RE.finditer(text.lower()):
        slug = _ALIASES[m.group(1)]
        if slug not in seen:
            seen.append(slug)
    return seen


def _restaurant_name(slug: str | None) -> str | None:
    return next((r["name"] for r in _SEED_RESTAURANTS if r["slug"] == slug), None)


def _price(level: int) -> str:
    return "₹" * max(1, min(int(level or 1), 4))


def _directory() -> str:
    """One line per restaurant for the system prompt (falls back to seed data if the DB is unavailable)."""
    try:
        rows = bs.list_restaurants()
        zones = {r["slug"]: sorted({t["zone"] for t in bs.list_tables(r["slug"])}) for r in rows}
    except Exception:
        rows, zones = [dict(r, slot_minutes=30) for r in _SEED_RESTAURANTS], {}
    lines = []
    for r in rows:
        close = r["hours_close"]
        last = (datetime.strptime(close, "%H:%M") - timedelta(minutes=bs.DEFAULT_DURATION)).strftime("%H:%M")
        z = ", ".join(zones.get(r["slug"], [])) or "ask"
        lines.append(f"- {r['name']} (restaurant_slug={r['slug']}, codes {r['code_prefix']}-XXXX): "
                     f"{', '.join(r['cuisine'])} · {r['area']} · {_price(r['price_level'])} (~₹{r['avg_cost_for_two']:,} "
                     f"for two) · rating {r['rating']} · tags: {', '.join(r['tags'])} · seatings {r['hours_open']}-{last} "
                     f"(closes {close}) · zones: {z}")
    return "\n".join(lines)


# ====================================================================== tools

class _NeedRestaurant(bs.BookingError):
    pass


def _err(e: Exception) -> str:
    msg = e.message if isinstance(e, bs.BookingError) else f"Unexpected error: {e}"
    out: dict[str, Any] = {"error": msg}
    if isinstance(e, _NeedRestaurant):
        out["needs_restaurant"] = True
        out["restaurants"] = list(_SLUGS)
    return json.dumps(out)


def _slug(explicit: str | None, state: dict | None) -> str:
    slug = resolve_restaurant(explicit) or (explicit or "").strip().lower() or (state or {}).get("current_restaurant")
    if not slug:
        raise _NeedRestaurant("No restaurant selected. Ask the guest which restaurant they mean before continuing.")
    return slug


@tool
def search_restaurants(cuisine: str | None = None, area: str | None = None, price_level: int | None = None,
                       tags: list[str] | None = None, party_size: int | None = None, date: str | None = None,
                       time: str | None = None) -> str:
    """Find Tablewise restaurants in Mumbai and their next open time slots. All filters are optional:
    cuisine (e.g. Italian, Japanese, Seafood, North Indian, Thali), area (Lower Parel, Bandra, Powai, Juhu, Colaba,
    Andheri), price_level 1-4 (1 = budget, 4 = splurge), tags (any of: rooftop, bar, live-music, pet-friendly,
    pure-veg), party_size, date YYYY-MM-DD (default today), time HH:MM (24h; slots at/after it)."""
    try:
        if date and "T" in date and not time:
            date, time = date[:10], date[11:16]
        rows = bs.search_restaurants(cuisine=cuisine, area=area, price_level=price_level, tags=tags,
                                     party_size=party_size, date=date, time=time)
        return json.dumps({"count": len(rows), "date": (date or datetime.now().date().isoformat())[:10],
                           "party_size": party_size or 2, "restaurants": rows})
    except Exception as e:
        return _err(e)


@tool
def check_availability(date: str, party_size: int, state: Annotated[dict, InjectedState],
                       time: str | None = None, zone: str | None = None, restaurant_slug: str | None = None) -> str:
    """Check which times have a free table at one restaurant. date: YYYY-MM-DD. party_size: guests (1-12).
    time: optional preferred time HH:MM (24h) - reports whether it is free plus nearest alternatives.
    zone: optional seating zone (window, garden, bar, private, rooftop, patio - depends on the restaurant).
    restaurant_slug: which restaurant; defaults to the currently selected one."""
    try:
        if not time and "T" in date:  # model sometimes sends a full ISO datetime
            time = date[11:16]
        r = bs.check_availability(_slug(restaurant_slug, state), date, party_size, time, zone)
        out = {"restaurant_slug": r["restaurant_slug"], "restaurant_name": r["restaurant_name"], "date": r["date"],
               "party_size": r["party_size"], "zone": r["zone"],
               "available_times": [s["time"] for s in r["slots"] if s["available"]]}
        for k in ("requested_time", "requested_available", "nearest_alternatives", "suggested_table"):
            if k in r:
                out[k] = r[k]
        return json.dumps(out)
    except Exception as e:
        return _err(e)


@tool
def create_booking(guest_name: str, party_size: int, date: str, time: str, state: Annotated[dict, InjectedState],
                   phone: str | None = None, email: str | None = None, zone: str | None = None,
                   notes: str | None = None, restaurant_slug: str | None = None, allergies: list[str] | None = None,
                   dietary: str | None = None, occasion: str | None = None,
                   special_requests: str | None = None) -> str:
    """Create a confirmed reservation. ONLY call after the guest has explicitly confirmed the recap.
    date: YYYY-MM-DD, time: HH:MM (24h). Provide phone or email. zone: optional seating zone.
    restaurant_slug: defaults to the currently selected one.
    allergies: list of any of nuts, peanuts, gluten, dairy, shellfish, fish, eggs, soy, sesame.
    dietary: veg | vegan | jain | halal | none. occasion: birthday | anniversary | business | date | none.
    special_requests: free text such as "cake at dessert" (max 500 chars). notes: anything else.
    When allergies are given the result includes allergy_check.avoid - dishes on that restaurant's menu to avoid -
    which you must name to the guest."""
    try:
        return json.dumps(allergens.attach_allergy_check(bs.create_booking(
            _slug(restaurant_slug, state), guest_name=guest_name, party_size=party_size,
            start_time=bs.combine(date, time), phone=phone, email=email, zone=zone, notes=notes, source="chat",
            allergies=allergies, dietary=dietary, occasion=occasion, special_requests=special_requests)))
    except Exception as e:
        return _err(e)


@tool
def modify_booking(code: str, state: Annotated[dict, InjectedState], date: str | None = None,
                   time: str | None = None, party_size: int | None = None, zone: str | None = None,
                   notes: str | None = None, restaurant_slug: str | None = None, allergies: list[str] | None = None,
                   dietary: str | None = None, occasion: str | None = None,
                   special_requests: str | None = None) -> str:
    """Change an existing booking identified by its code (e.g. EMB-7K2P). Any of date (YYYY-MM-DD), time (HH:MM),
    party_size, zone, notes, allergies (replaces the list; values as in create_booking), dietary, occasion,
    special_requests may be changed; omitted fields keep their current value. restaurant_slug is optional (the code
    identifies the restaurant). With allergies the result includes allergy_check.avoid - name those dishes."""
    try:
        slug = resolve_restaurant(restaurant_slug) if restaurant_slug else None
        start = None
        if date or time:
            cur = datetime.fromisoformat(bs.get_booking(code, slug)["start_time"])
            start = bs.combine(date or cur.date().isoformat(), time or cur.strftime("%H:%M"))
        return json.dumps(allergens.attach_allergy_check(bs.modify_booking(
            code, start_time=start, party_size=party_size, zone=zone, notes=notes, restaurant_slug=slug,
            allergies=allergies, dietary=dietary, occasion=occasion, special_requests=special_requests)))
    except Exception as e:
        return _err(e)


@tool
def check_menu_allergens(allergies: list[str], state: Annotated[dict, InjectedState],
                         restaurant_slug: str | None = None) -> str:
    """Cross-check the guest's allergies against one restaurant's menu (menu.md) and list the dishes to avoid.
    allergies: any of nuts, peanuts, gluten, dairy, shellfish, fish, eggs, soy, sesame.
    restaurant_slug: defaults to the currently selected one. Use it before the booking recap when allergies come up."""
    try:
        check = allergens.allergy_check(_slug(restaurant_slug, state), bs.normalize_allergies(allergies))
        return json.dumps(check or {"allergies": [], "avoid": {}, "note": "No allergies to check."})
    except Exception as e:
        return _err(e)


@tool
def cancel_booking(code: str, state: Annotated[dict, InjectedState], restaurant_slug: str | None = None) -> str:
    """Cancel the booking with this code (e.g. EMB-7K2P). restaurant_slug is optional."""
    try:
        return json.dumps(bs.cancel_booking(code, resolve_restaurant(restaurant_slug) if restaurant_slug else None))
    except Exception as e:
        return _err(e)


@tool
def lookup_booking(code: str, state: Annotated[dict, InjectedState], restaurant_slug: str | None = None) -> str:
    """Look up a booking by its code (e.g. EMB-7K2P) to see its details, restaurant and status."""
    try:
        return json.dumps(allergens.attach_allergy_check(
            bs.get_booking(code, resolve_restaurant(restaurant_slug) if restaurant_slug else None)))
    except Exception as e:
        return _err(e)


TOOLS = [search_restaurants, check_availability, create_booking, modify_booking, cancel_booking, lookup_booking,
         check_menu_allergens]
BOOKING_ACTIONS = {"create_booking": "created", "modify_booking": "modified", "cancel_booking": "cancelled"}
_CODE_RE = re.compile(r"\b[A-Z]{2,3}-[A-Z0-9]{4}\b")


# ====================================================================== state & helpers

class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    intent: str
    retrieved_docs: list[dict]
    tool_results: list[dict]
    booking_draft: dict | None
    current_restaurant: str | None


class Route(BaseModel):
    """Classify the guest's latest message."""
    intent: Literal["info", "booking", "discover", "smalltalk", "offtopic"] = Field(
        description="info = questions about a restaurant; booking = availability/reservations/changes/cancellations "
                    "or continuing a booking conversation; discover = finding or comparing restaurants; "
                    "smalltalk = greetings/thanks/chit-chat; offtopic = requests unrelated to dining on Tablewise")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _now_context() -> str:
    now = datetime.now()
    days = ", ".join(f"{(now.date() + timedelta(days=i)):%A}={(now.date() + timedelta(days=i)).isoformat()}"
                     for i in range(8))
    return (f"Current server date/time (Mumbai): {now:%A %d %B %Y, %H:%M}. Today is {now.date().isoformat()}; "
            f"tomorrow is {(now.date() + timedelta(days=1)).isoformat()}. Upcoming days: {days}.")


def _format_docs(docs: list[dict]) -> str:
    return "\n\n".join(f"[{d['index']}] ({d.get('restaurant_slug')}/{d['source']} > {d['section']})\n{d['text']}"
                       for d in docs) or "(none)"


def _last_human(msgs: list[AnyMessage]) -> str:
    for m in reversed(msgs):
        if isinstance(m, HumanMessage):
            return _text(m.content)
    return ""


def _sanitize(msgs: list[AnyMessage], limit: int = 40) -> list[AnyMessage]:
    """Drop dangling tool calls / orphan tool results and trim to a window starting on a human turn."""
    answered = {m.tool_call_id for m in msgs if isinstance(m, ToolMessage)}
    called: set[str] = set()
    out: list[AnyMessage] = []
    for m in msgs:
        if isinstance(m, AIMessage) and m.tool_calls:
            if all(tc["id"] in answered for tc in m.tool_calls):
                out.append(m)
                called.update(tc["id"] for tc in m.tool_calls)
            elif _text(m.content):
                out.append(AIMessage(content=_text(m.content)))
        elif isinstance(m, ToolMessage):
            if m.tool_call_id in called:
                out.append(m)
        else:
            out.append(m)
    out = out[-limit:]
    while out and not isinstance(out[0], HumanMessage):
        out.pop(0)
    return out


def _text_history(msgs: list[AnyMessage], limit: int = 30) -> list[AnyMessage]:
    """Plain-text transcript (no tool blocks), consecutive same-role turns merged."""
    out: list[AnyMessage] = []
    for m in msgs[-limit:]:
        if isinstance(m, (HumanMessage, AIMessage)):
            t = _text(m.content).strip()
            if not t:
                continue
            if out and type(out[-1]) is type(m):
                out[-1] = type(m)(content=_text(out[-1].content) + "\n\n" + t)
            else:
                out.append(HumanMessage(content=t) if isinstance(m, HumanMessage) else AIMessage(content=t))
    while out and not isinstance(out[0], HumanMessage):
        out.pop(0)
    return out


_OFF_TOPIC = re.compile(r"\b(python|javascript|code|coding|program|homework|essay|poem|stocks?|crypto|bitcoin|"
                        r"weather|news|election|politics|movie|translate|math)\b")
_ON_TOPIC = re.compile(r"menu|dish|food|dinner|lunch|brunch|wine|drink|cocktail|allerg|vegan|veg\b|gluten|table|"
                       r"reserv|book|park|hour|open|event|chef|private|cancel|restaurant|thali|biryani|sushi|pizza|"
                       r"[a-z]{3}-[a-z0-9]{4}|" + _ALIAS_RE.pattern)
_DISCOVER = re.compile(
    r"\b(recommend\w*|suggest\w*|restaurants?|places?|where (?:can|should|to)|options|rooftop|cuisine|italian|"
    r"pizza|pasta|japanese|sushi|ramen|pan[- ]asian|seafood|fish|coastal|malvani|thali|gujarati|rajasthani|"
    r"north indian|mughlai|biryani|kebabs?|pure[- ]veg|vegetarian|cheap|budget|affordable|splurge|fancy|"
    r"pet[- ]friendly|dog[- ]friendly|live[- ]music|bar|bandra|juhu|powai|colaba|andheri|lower parel)\b")


def _heuristic_intent(text: str, msgs: list[AnyMessage]) -> str:
    t = text.lower()
    if re.search(r"\b[a-z]{2,3}-[a-z0-9]{4}\b|\bbook|reserv|cancel|reschedul|modify|change my", t):
        return "booking"
    if re.fullmatch(r"\s*(hi|hello|hey|thanks|thank you|good (evening|morning|afternoon)|cheers)[!. ]*", t):
        return "smalltalk"
    if _OFF_TOPIC.search(t) and not _ON_TOPIC.search(t):
        return "offtopic"
    if _DISCOVER.search(t) and not mentioned_restaurants(t):
        return "discover"
    if re.search(r"availab|table for|\bparty of\b|tonight at|tomorrow at", t):
        return "booking"
    # short reply continuing a booking conversation ("yes", "Ana, 98200 12345")
    prior = [m for m in msgs[:-1] if isinstance(m, AIMessage)]
    if prior and len(t.split()) <= 8 and re.search(r"confirm|book|reserv|name|phone|email|which restaurant",
                                                   _text(prior[-1].content).lower()):
        return "booking"
    return "info"


def _write_tokens(writer, text: str) -> None:
    for piece in re.findall(r"\S+\s*|\s+", text):
        writer({"type": "token", "content": piece})


# ====================================================================== prompts

ROUTER_PROMPT = """You route messages for the Tablewise restaurant concierge (six restaurants in Mumbai).
Classify the guest's LATEST message:
- booking: checking availability, making/changing/confirming/cancelling a reservation, giving booking details
  (restaurant, party size, date, time, name, phone, email, booking code like EMB-7K2P), or replying yes/no to a
  booking question.
- discover: finding, recommending or comparing restaurants - by cuisine, area, budget, vibe (rooftop, live music,
  pet-friendly, pure-veg) or "who has a table tonight".
- info: questions about a specific restaurant or Tablewise - menu, dishes, allergens, diets, hours, location,
  parking, policies, events, private dining.
- smalltalk: greetings, thanks, chit-chat with no information need.
- offtopic: anything unrelated to dining at these restaurants - coding, homework, news, finance, general trivia.
Use the recent conversation: a short reply that continues a booking flow is booking."""

GUARDRAIL_REPLY = ("I'm the Tablewise concierge, so I can only help with our Mumbai restaurants - finding a place, "
                   "reservations, menus, allergens, opening hours and policies. Is there anything I can help you "
                   "with for your next meal out?")

BOOKING_SYSTEM = """You are the Tablewise concierge: a warm, polished and concise maitre d' for six restaurants \
in Mumbai. Prices are in Indian rupees (₹).
{now}

Restaurants:
{directory}

Currently selected restaurant: {current}

House rules: tables are held 90 minutes; seatings every 30 minutes from opening until last seating (90 minutes \
before close); online parties of 1-12.

How to work:
1. Discovery: when the guest wants ideas or is choosing ("rooftop in Bandra", "seafood tonight for 4"), call \
search_restaurants with the filters they gave (cuisine, area, price_level 1-4, tags, party_size, date, time). \
Present 2-4 matches in one line each with their next open slots (the app also shows cards) and offer to book.
2. Every availability/booking tool takes restaurant_slug. Use the currently selected restaurant unless the guest \
names another one. If no restaurant is selected, or the request could mean more than one restaurant, ASK the guest \
which restaurant they want before checking availability or booking - never guess.
3. Resolve relative dates and times ("tomorrow at 8" -> tomorrow's YYYY-MM-DD, 20:00) from the current date. \
Dinner times without am/pm mean pm.
4. Call check_availability before offering a time. If the requested time is taken, offer the nearest alternatives.
5. To book you need: restaurant, party size, date, time, the guest's name, and a phone number or email. Zone, \
occasion and special requests are optional.
6. Once you have those details and BEFORE the recap, ask exactly: "Any allergies or dietary requirements?" (you may \
also ask whether it's a special occasion) unless the guest already told you. Map answers to allergies (nuts, \
peanuts, gluten, dairy, shellfish, fish, eggs, soy, sesame), dietary (veg, vegan, jain, halal, none) and occasion \
(birthday, anniversary, business, date, none); anything else goes in special_requests. If the guest has allergies, \
call check_menu_allergens for that restaurant and name the dishes to avoid.
7. BEFORE calling create_booking, recap every detail (restaurant, name, party size, weekday + date, time, zone, \
contact, allergies, dietary, occasion, special requests) and ask the guest to confirm. Only call create_booking \
after the guest explicitly confirms in a later message - even if they gave every detail up front. Pass date as \
YYYY-MM-DD and time as HH:MM separately, and pass allergies/dietary/occasion/special_requests as their own arguments \
(also to modify_booking when they change).
8. For changes or cancellations, get the booking code (e.g. EMB-7K2P), call lookup_booking, then modify_booking or \
cancel_booking. A direct request to cancel a specific code counts as confirmation.
9. After a successful booking, give the booking code in bold and mention the restaurant's cancellation policy. \
If the result has allergy_check, name the dishes listed in allergy_check.avoid so the guest knows what to skip.
Never invent restaurants, availability, tables or booking codes - only state what tools return. Speak in 12-hour \
times (8:00 pm). Keep replies short and elegant; use bold sparingly for key details.

Relevant information (cite as [n] only if you rely on it):
{docs}"""

RESPOND_SYSTEM = """You are the Tablewise concierge for six restaurants in Mumbai. Warm, elegant, concise.
{now}
Currently selected restaurant: {current}

Answer the guest's latest message using ONLY the information below. Cite the sources you use inline as [1], [2] \
matching the numbers, and name the restaurant when it isn't obvious. If the information doesn't cover the question, \
say so graciously and suggest calling the restaurant. Keep it to 2-6 sentences or a short list. If natural, offer to \
reserve a table.

Information:
{docs}"""

SMALLTALK_SYSTEM = """You are the Tablewise concierge for six restaurants in Mumbai. {now} Reply briefly \
(1-2 sentences), warmly and with a little charm. Offer to help find a restaurant, book a table, or answer questions \
about menus, allergens, hours or policies."""


# ====================================================================== nodes

async def router(state: AgentState) -> dict:
    writer = get_stream_writer()
    writer({"type": "node", "node": "router", "status": "start"})
    msgs = state["messages"]
    last = _last_human(msgs)
    intent: str | None = None
    if LLM_ENABLED:
        history = _text_history(msgs[:-1], limit=8)
        transcript = "\n".join(f"{'Guest' if isinstance(m, HumanMessage) else 'Concierge'}: {_text(m.content)[:400]}"
                               for m in history)
        try:
            route = await _llm(256).with_structured_output(Route).ainvoke([
                SystemMessage(content=ROUTER_PROMPT),
                HumanMessage(content=f"Recent conversation:\n{transcript or '(none)'}\n\nLatest guest message:\n{last}"),
            ])
            intent = route.intent if isinstance(route, Route) else dict(route).get("intent")
        except Exception:
            metrics.LLM_ERRORS.inc()
            intent = None  # fall back to heuristics (e.g. model without forced tool_choice support)
    if intent not in INTENTS:
        intent = _heuristic_intent(last, msgs)
    update: dict[str, Any] = {"intent": intent, "tool_results": []}
    named = mentioned_restaurants(last)
    if len(named) == 1:  # the guest picked a restaurant in chat
        update["current_restaurant"] = named[0]
    writer({"type": "node", "node": "router", "status": "end", "intent": intent,
            "restaurant_slug": update.get("current_restaurant", state.get("current_restaurant"))})
    return update


async def retrieve(state: AgentState) -> dict:
    writer = get_stream_writer()
    writer({"type": "node", "node": "retrieve", "status": "start"})
    humans = [_text(m.content) for m in state["messages"] if isinstance(m, HumanMessage)]
    query = humans[-1] if humans else ""
    if len(query.split()) < 5 and len(humans) > 1:  # "yes please" -> add previous turn for context
        query = humans[-2] + " " + query
    slug = None if state.get("intent") == "discover" else state.get("current_restaurant")
    docs = await asyncio.to_thread(rag.retrieve, query, 4, slug)
    return {"retrieved_docs": docs}


async def booking_agent(state: AgentState) -> dict:
    writer = get_stream_writer()
    writer({"type": "node", "node": "booking_agent", "status": "start"})
    msgs = state["messages"]
    current = state.get("current_restaurant")
    # collect tool results produced since the last human turn, and track the booking draft + chosen restaurant
    tool_results, draft = [], dict(state.get("booking_draft") or {})
    for m in reversed(msgs):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, ToolMessage):
            try:
                tool_results.insert(0, {"name": m.name, "result": json.loads(m.content)})
            except (TypeError, ValueError):
                tool_results.insert(0, {"name": m.name, "result": m.content})
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                if tc["name"] in ("check_availability", "create_booking"):
                    draft.update({k: v for k, v in tc["args"].items() if v is not None})
                    picked = resolve_restaurant(tc["args"].get("restaurant_slug"))
                    if picked and current is None:
                        current = picked
    for tr in reversed(tool_results):  # latest successful restaurant-scoped result wins
        res = tr["result"]
        if isinstance(res, dict) and res.get("restaurant_slug") and "error" not in res:
            current = res["restaurant_slug"]
            break
    update: dict[str, Any] = {"tool_results": tool_results, "booking_draft": draft or None,
                              "current_restaurant": current}

    if not LLM_ENABLED:
        update["messages"] = [_offline_booking(msgs, writer, state.get("intent"), current)]
        return update

    system = SystemMessage(content=BOOKING_SYSTEM.format(
        now=_now_context(), directory=_directory(),
        current=f"{_restaurant_name(current)} (restaurant_slug={current})" if current else "none - ask if needed",
        docs=_format_docs(state.get("retrieved_docs") or [])))
    msg = await _llm(1500).bind_tools(TOOLS).ainvoke([system] + _sanitize(msgs))
    update["messages"] = [msg]
    return update


async def guardrail(state: AgentState) -> dict:
    """Politely decline off-topic requests: no retrieval, no tools, no LLM call."""
    writer = get_stream_writer()
    writer({"type": "node", "node": "guardrail", "status": "start"})
    _write_tokens(writer, GUARDRAIL_REPLY)
    return {"messages": [AIMessage(content=GUARDRAIL_REPLY)]}


async def respond(state: AgentState) -> dict:
    writer = get_stream_writer()
    writer({"type": "node", "node": "respond", "status": "start"})
    intent = state.get("intent")
    if intent in ("booking", "discover"):
        # booking_agent already wrote (and streamed) the guest-facing reply, grounded in the same docs. If a booking
        # with allergies came back this turn and the reply didn't name the dishes to avoid, add the menu check.
        note = allergy_followup(state.get("tool_results") or [], _last_ai_text(state["messages"]))
        if not note:
            return {}
        _write_tokens(writer, "\n\n" + note)
        return {"messages": [AIMessage(content=note)]}
    docs = state.get("retrieved_docs") or []
    current = state.get("current_restaurant")
    if not LLM_ENABLED:
        if intent == "smalltalk":
            text = ("Welcome to Tablewise. I'm your concierge - tell me what you're in the mood for and I'll find "
                    "a restaurant, check a table, or answer questions about menus, allergens and hours.")
        elif docs:
            top = docs[0]
            snippet = top["text"].split("\n\n", 1)[-1][:700].strip()
            text = (f"*(Offline demo mode - set an LLM API key for full answers.)* Here's the most relevant "
                    f"passage [1]:\n\n> {snippet.replace(chr(10), chr(10) + '> ')}")
        else:
            text = "I couldn't find that in our guides - please call the restaurant directly."
        _write_tokens(writer, text)
        return {"messages": [AIMessage(content=text)]}

    if intent == "smalltalk":
        system = SMALLTALK_SYSTEM.format(now=_now_context())
    else:
        system = RESPOND_SYSTEM.format(now=_now_context(), current=_restaurant_name(current) or "none",
                                       docs=_format_docs(docs))
    msg = await _llm(1200).ainvoke([SystemMessage(content=system)] + _text_history(state["messages"]))
    return {"messages": [AIMessage(content=_text(msg.content), id=msg.id)]}


def _last_ai_text(msgs: list[AnyMessage]) -> str:
    for m in reversed(msgs):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, AIMessage) and _text(m.content):
            return _text(m.content)
    return ""


def allergy_followup(tool_results: list[dict], reply: str) -> str | None:
    """Allergy note for the latest booking result (create/modify/lookup) with allergies, unless `reply` already
    names every dish to avoid."""
    for tr in reversed(tool_results):
        res = tr.get("result")
        if tr.get("name") not in ("create_booking", "modify_booking", "lookup_booking") or not isinstance(res, dict):
            continue
        check = res.get("allergy_check")
        if not check:
            return None
        dishes = {d for ds in check.get("avoid", {}).values() for d in ds}
        low = reply.lower()
        if check["note"] in reply or (dishes and all(d.lower() in low for d in dishes)):
            return None
        return check["note"]
    return None


# ====================================================================== offline mode (no API key)

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_CUISINE_WORDS = {"italian": "Italian", "pizza": "Pizza", "pasta": "Italian", "japanese": "Japanese",
                  "sushi": "Japanese", "ramen": "Japanese", "pan-asian": "Pan-Asian", "seafood": "Seafood",
                  "fish": "Seafood", "coastal": "Coastal", "malvani": "Malvani", "thali": "Thali",
                  "gujarati": "Gujarati", "rajasthani": "Rajasthani", "north indian": "North Indian",
                  "mughlai": "Mughlai", "biryani": "Mughlai", "kebab": "Mughlai", "wood-fire": "Wood-fire",
                  "european": "Modern European"}
_AREAS = ("lower parel", "bandra", "powai", "juhu", "colaba", "andheri")
_TAG_WORDS = {"rooftop": "rooftop", "live music": "live-music", "live-music": "live-music",
              "pet-friendly": "pet-friendly", "pet friendly": "pet-friendly", "dog": "pet-friendly",
              "pure veg": "pure-veg", "pure-veg": "pure-veg", "vegetarian": "pure-veg", " bar": "bar"}


def _parse_when(low: str) -> dict[str, Any]:
    today = datetime.now().date()
    day = today
    if "tomorrow" in low:
        day = today + timedelta(days=1)
    else:
        iso = re.search(r"\d{4}-\d{2}-\d{2}", low)
        wd = next((i for i, w in enumerate(_WEEKDAYS) if w in low), None)
        if iso:
            day = datetime.fromisoformat(iso.group(0)).date()
        elif wd is not None:
            day = today + timedelta(days=(wd - today.weekday()) % 7 or 7)
    party = re.search(r"(?:for|party of|table for)\s+(\d{1,2})\b|(\d{1,2})\s*(?:people|guests|persons|pax)", low)
    size = int(next(g for g in party.groups() if g)) if party else 2
    tm = re.search(r"(?:at|@)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?|(\d{1,2})(?::(\d{2}))?\s*(am|pm)", low)
    out: dict[str, Any] = {"date": day.isoformat(), "party_size": size}
    if tm:
        h, mnt, ap = (tm.group(1), tm.group(2), tm.group(3)) if tm.group(1) else (tm.group(4), tm.group(5), tm.group(6))
        hour = int(h)
        if ap == "am" and hour == 12:
            hour = 0
        elif ap != "am" and hour < 12:  # pm, or no suffix: dinner times mean pm
            hour += 12
        out["time"] = f"{hour:02d}:{mnt or '00'}"
    return out


def _offline_summary(results: list[dict]) -> str:
    lines = []
    for r in results:
        if "error" in r:
            if r.get("needs_restaurant"):
                lines.append("Which restaurant would you like? Options: " +
                             ", ".join(_restaurant_name(s) or s for s in r.get("restaurants", [])) + ".")
            else:
                lines.append(f"Hmm - {r['error']}")
        elif "restaurants" in r:
            if not r["restaurants"]:
                lines.append("I couldn't find a restaurant matching that - try fewer filters.")
            for x in r["restaurants"]:
                slots = ", ".join(x["next_slots"]) or "no open slots"
                lines.append(f"- **{x['name']}** - {', '.join(x['cuisine'])}, {x['area']} "
                             f"({_price(x['price_level'])}). Next tables: {slots}.")
        elif "code" in r:
            lines.append(f"Booking **{r['code']}** at {r.get('restaurant_name')} for {r['guest_name']} "
                         f"({r['party_size']} guests) on {r['start_time'].replace('T', ' at ')[:16]} at table "
                         f"{r['table_name']} is **{r['status']}**.")
            if r.get("allergy_check"):
                lines.append(r["allergy_check"]["note"])
        elif "available_times" in r:
            where = r.get("restaurant_name") or ""
            if r.get("requested_time"):
                ok = r.get("requested_available")
                lines.append(f"{where}: {r['requested_time']} on {r['date']} for {r['party_size']} is "
                             f"{'**available**' if ok else 'taken'}." +
                             ("" if ok else f" Nearest options: {', '.join(r.get('nearest_alternatives') or []) or 'none'}."))
            else:
                lines.append(f"{where}: open times on {r['date']} for {r['party_size']}: "
                             f"{', '.join(r['available_times']) or 'none'}.")
    lines.append("\n*(Offline demo mode: I can search restaurants, check availability, look up and cancel bookings. "
                 "Use the booking panel to reserve, or set an LLM API key for the full concierge.)*")
    return "\n".join(lines)


def _offline_booking(msgs: list[AnyMessage], writer, intent: str | None = None,
                     current: str | None = None) -> AIMessage:
    last = msgs[-1]
    if isinstance(last, ToolMessage):
        results = []
        for m in reversed(msgs):
            if not isinstance(m, ToolMessage):
                break
            try:
                results.insert(0, json.loads(m.content))
            except (TypeError, ValueError):
                results.insert(0, {"error": str(m.content)})
        text = _offline_summary(results)
        _write_tokens(writer, text)
        return AIMessage(content=text)

    text = _last_human(msgs)
    low = text.lower()
    code = _CODE_RE.search(text.upper())
    if code and "cancel" in low:
        call = {"name": "cancel_booking", "args": {"code": code.group(0)}}
    elif code:
        call = {"name": "lookup_booking", "args": {"code": code.group(0)}}
    elif intent == "discover":
        when = _parse_when(low)
        args: dict[str, Any] = {"party_size": when["party_size"], "date": when["date"]}
        if "time" in when:
            args["time"] = when["time"]
        cuisine = next((v for k, v in _CUISINE_WORDS.items() if k in low), None)
        area = next((a for a in _AREAS if a in low), None)
        tags = sorted({v for k, v in _TAG_WORDS.items() if k in f" {low}"})
        if cuisine:
            args["cuisine"] = cuisine
        if area:
            args["area"] = area
        if tags:
            args["tags"] = tags
        call = {"name": "search_restaurants", "args": args}
    else:
        args = _parse_when(low)
        zone = next((z for z in bs.ZONES if z in low), None)
        if zone:
            args["zone"] = zone
        if current:
            args["restaurant_slug"] = current
        call = {"name": "check_availability", "args": args}
    return AIMessage(content="", tool_calls=[{**call, "id": f"offline_{uuid.uuid4().hex[:10]}", "type": "tool_call"}])


# ====================================================================== graph

def _after_router(state: AgentState) -> str:
    return {"smalltalk": "respond", "offtopic": "guardrail"}.get(state.get("intent") or "", "retrieve")


def _after_retrieve(state: AgentState) -> str:
    return "booking_agent" if state.get("intent") in ("booking", "discover") else "respond"


def _after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    return "tools" if isinstance(last, AIMessage) and last.tool_calls else "respond"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("router", router)
    g.add_node("retrieve", retrieve)
    g.add_node("booking_agent", booking_agent)
    g.add_node("tools", ToolNode(TOOLS))
    g.add_node("respond", respond)
    g.add_node("guardrail", guardrail)
    g.add_edge(START, "router")
    g.add_conditional_edges("router", _after_router, ["retrieve", "respond", "guardrail"])
    g.add_edge("guardrail", END)
    g.add_conditional_edges("retrieve", _after_retrieve, ["booking_agent", "respond"])
    g.add_conditional_edges("booking_agent", _after_agent, ["tools", "respond"])
    g.add_edge("tools", "booking_agent")
    g.add_edge("respond", END)
    return g.compile(checkpointer=MemorySaver())


GRAPH = build_graph()


async def run_chat(message: str, thread_id: str, restaurant_slug: str | None = None) -> AsyncIterator[dict]:
    """Run one guest turn and yield UI events. restaurant_slug (from the restaurant page) selects the restaurant."""
    started = _time.perf_counter()
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 30}
    inputs: dict[str, Any] = {"messages": [HumanMessage(content=message)], "intent": "", "retrieved_docs": [],
                              "tool_results": []}
    if restaurant_slug:
        inputs["current_restaurant"] = resolve_restaurant(restaurant_slug) or restaurant_slug
    intent, docs, streamed = "", [], []
    try:
        async for mode, chunk in GRAPH.astream(inputs, config, stream_mode=["custom", "messages", "updates"]):
            if mode == "custom":
                if chunk.get("type") == "node" and chunk.get("intent"):
                    intent = chunk["intent"]
                if chunk.get("type") == "token":
                    streamed.append(chunk["content"])
                yield chunk
            elif mode == "messages":
                msg, meta = chunk
                if isinstance(msg, AIMessageChunk) and meta.get("langgraph_node") in ("booking_agent", "respond"):
                    t = _text(msg.content)
                    if t:
                        streamed.append(t)
                        yield {"type": "token", "content": t}
            elif mode == "updates":
                for node, upd in (chunk or {}).items():
                    if not isinstance(upd, dict):
                        continue
                    if node == "retrieve":
                        docs = upd.get("retrieved_docs") or []
                    elif node == "booking_agent":
                        for m in upd.get("messages") or []:
                            if isinstance(m, AIMessage) and m.tool_calls:
                                if streamed and not streamed[-1].endswith("\n"):
                                    yield {"type": "token", "content": "\n\n"}
                                    streamed.append("\n\n")
                                yield {"type": "node", "node": "tools", "status": "start"}
                                for tc in m.tool_calls:
                                    yield {"type": "tool", "id": tc["id"], "name": tc["name"], "args": tc["args"],
                                           "status": "start"}
                    elif node == "tools":
                        for m in upd.get("messages") or []:
                            if not isinstance(m, ToolMessage):
                                continue
                            try:
                                payload = json.loads(m.content)
                            except (TypeError, ValueError):
                                payload = {"error": str(m.content)}
                            yield {"type": "tool", "id": m.tool_call_id, "name": m.name, "status": "end",
                                   "result": payload}
                            if m.name in BOOKING_ACTIONS and isinstance(payload, dict) and "code" in payload:
                                yield {"type": "booking", "action": BOOKING_ACTIONS[m.name], "booking": payload}
                            if (m.name == "search_restaurants" and isinstance(payload, dict)
                                    and payload.get("restaurants")):
                                yield {"type": "restaurants", "restaurants": payload["restaurants"]}
        full = "".join(streamed)
        if intent == "info":
            sources = docs
        else:  # booking/discover: only chips for docs the agent actually cited
            sources = [d for d in docs if f"[{d['index']}]" in full]
        if sources:
            yield {"type": "sources", "sources": sources}
    except Exception as e:  # surface errors to the UI instead of a dead stream
        if LLM_ENABLED:
            metrics.LLM_ERRORS.inc()
        yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
    finally:
        metrics.CHAT_REQUESTS.labels(intent=intent or "unknown").inc()
        metrics.CHAT_LATENCY.observe(_time.perf_counter() - started)
    yield {"type": "done"}

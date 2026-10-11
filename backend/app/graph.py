"""LangGraph concierge: router -> retrieve -> booking_agent <-> tools -> respond.

Streams UI events (node transitions, tokens, tool calls, sources, bookings) via `run_chat`.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Literal, Optional, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from . import booking_service as bs
from . import rag

_BACKEND = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND / ".env")
load_dotenv(_BACKEND.parent / ".env")

PROVIDER = (os.getenv("LLM_PROVIDER") or ("groq" if os.getenv("GROQ_API_KEY") else "anthropic")).lower()
_DEFAULT_MODELS = {"groq": "openai/gpt-oss-120b", "anthropic": "claude-sonnet-4-5"}
MODEL = os.getenv("LLM_MODEL") or _DEFAULT_MODELS.get(PROVIDER, "openai/gpt-oss-120b")
LLM_ENABLED = bool(os.getenv("GROQ_API_KEY") if PROVIDER == "groq" else os.getenv("ANTHROPIC_API_KEY"))


def _llm(max_tokens: int = 1500):
    if PROVIDER == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=MODEL, max_tokens=max_tokens, max_retries=2, temperature=0.3)
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=MODEL, max_tokens=max_tokens, max_retries=2)


# ====================================================================== tools

def _err(e: Exception) -> str:
    msg = e.message if isinstance(e, bs.BookingError) else f"Unexpected error: {e}"
    return json.dumps({"error": msg})


@tool
def check_availability(date: str, party_size: int, time: Optional[str] = None, zone: Optional[str] = None) -> str:
    """Check which times have a free table. date: YYYY-MM-DD. party_size: number of guests (1-12).
    time: optional preferred time HH:MM (24h) - reports whether it is free plus nearest alternatives.
    zone: optional seating preference: window, garden, bar or private."""
    try:
        if not time and "T" in date:  # model sometimes sends a full ISO datetime
            time = date[11:16]
        r = bs.check_availability(date, party_size, time, zone)
        out = {"date": r["date"], "party_size": r["party_size"], "zone": r["zone"],
               "available_times": [s["time"] for s in r["slots"] if s["available"]]}
        for k in ("requested_time", "requested_available", "nearest_alternatives", "suggested_table"):
            if k in r:
                out[k] = r[k]
        return json.dumps(out)
    except Exception as e:
        return _err(e)


@tool
def create_booking(guest_name: str, party_size: int, date: str, time: str, phone: Optional[str] = None,
                   email: Optional[str] = None, zone: Optional[str] = None, notes: Optional[str] = None) -> str:
    """Create a confirmed reservation. ONLY call after the guest has explicitly confirmed the recap.
    date: YYYY-MM-DD, time: HH:MM (24h). Provide phone or email. zone: window|garden|bar|private (optional).
    notes: allergies, occasions, requests (optional)."""
    try:
        return json.dumps(bs.create_booking(guest_name=guest_name, party_size=party_size,
                                            start_time=bs.combine(date, time), phone=phone, email=email,
                                            zone=zone, notes=notes))
    except Exception as e:
        return _err(e)


@tool
def modify_booking(code: str, date: Optional[str] = None, time: Optional[str] = None,
                   party_size: Optional[int] = None, zone: Optional[str] = None, notes: Optional[str] = None) -> str:
    """Change an existing booking identified by its code (EV-XXXX). Any of date (YYYY-MM-DD), time (HH:MM),
    party_size, zone, notes may be changed; omitted fields keep their current value."""
    try:
        start = None
        if date or time:
            cur = datetime.fromisoformat(bs.get_booking(code)["start_time"])
            start = bs.combine(date or cur.date().isoformat(), time or cur.strftime("%H:%M"))
        return json.dumps(bs.modify_booking(code, start_time=start, party_size=party_size, zone=zone, notes=notes))
    except Exception as e:
        return _err(e)


@tool
def cancel_booking(code: str) -> str:
    """Cancel the booking with this code (EV-XXXX)."""
    try:
        return json.dumps(bs.cancel_booking(code))
    except Exception as e:
        return _err(e)


@tool
def lookup_booking(code: str) -> str:
    """Look up a booking by its code (EV-XXXX) to see its details and status."""
    try:
        return json.dumps(bs.get_booking(code))
    except Exception as e:
        return _err(e)


TOOLS = [check_availability, create_booking, modify_booking, cancel_booking, lookup_booking]
BOOKING_ACTIONS = {"create_booking": "created", "modify_booking": "modified", "cancel_booking": "cancelled"}


# ====================================================================== state & helpers

class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    intent: str
    retrieved_docs: list[dict]
    tool_results: list[dict]
    booking_draft: Optional[dict]


class Route(BaseModel):
    """Classify the guest's latest message."""
    intent: Literal["info", "booking", "smalltalk"] = Field(
        description="info = restaurant questions; booking = availability/reservations/changes/cancellations or "
                    "continuing a booking conversation; smalltalk = greetings/thanks/chit-chat")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _now_context() -> str:
    now = datetime.now()
    days = ", ".join(f"{(now.date() + timedelta(days=i)):%A}={(now.date() + timedelta(days=i)).isoformat()}"
                     for i in range(0, 8))
    return (f"Current server date/time: {now:%A %d %B %Y, %H:%M}. Today is {now.date().isoformat()}; tomorrow is "
            f"{(now.date() + timedelta(days=1)).isoformat()}. Upcoming days: {days}.")


def _format_docs(docs: list[dict]) -> str:
    return "\n\n".join(f"[{d['index']}] ({d['source']} > {d['section']})\n{d['text']}" for d in docs) or "(none)"


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


def _heuristic_intent(text: str, msgs: list[AnyMessage]) -> str:
    t = text.lower()
    if re.search(r"\bev-[a-z0-9]{4}\b|\bbook|reserv|availab|table for|cancel|reschedul|modify|change my|"
                 r"\bparty of\b|tonight at|tomorrow at", t):
        return "booking"
    if re.fullmatch(r"\s*(hi|hello|hey|thanks|thank you|good (evening|morning|afternoon)|cheers)[!. ]*", t):
        return "smalltalk"
    # short reply continuing a booking conversation ("yes", "Ana, 555-1234")
    prior = [m for m in msgs[:-1] if isinstance(m, AIMessage)]
    if prior and len(t.split()) <= 8 and re.search(r"confirm|book|reserv|name|phone|email", _text(prior[-1].content).lower()):
        return "booking"
    return "info"


def _write_tokens(writer, text: str) -> None:
    for piece in re.findall(r"\S+\s*|\s+", text):
        writer({"type": "token", "content": piece})


# ====================================================================== prompts

ROUTER_PROMPT = """You route messages for the Ember & Vine restaurant concierge.
Classify the guest's LATEST message:
- booking: checking availability, making/changing/confirming/cancelling a reservation, giving booking details
  (party size, date, time, name, phone, email, booking code like EV-7K2P), or replying yes/no to a booking question.
- info: questions about the restaurant - menu, dishes, allergens, diets, hours, location, parking, policies, events,
  private dining, wine, corkage.
- smalltalk: greetings, thanks, chit-chat with no information need.
Use the recent conversation: a short reply that continues a booking flow is booking."""

BOOKING_SYSTEM = """You are the reservations concierge for Ember & Vine, an upscale wood-fire restaurant and natural \
wine bar in San Francisco. You are warm, polished and concise - a great maitre d'.
{now}

House rules: seatings every 30 minutes from 17:00 to 22:00 (last seating); tables are held 90 minutes; online parties of \
1-12 (larger parties: events@emberandvine.com). Seating zones: window, garden, bar, private.

How to work:
1. Resolve relative dates and times ("tomorrow at 8" -> tomorrow's YYYY-MM-DD, 20:00) from the current date above. \
Dinner times without am/pm mean pm.
2. Call check_availability before offering a time. If the requested time is taken, offer the nearest alternatives.
3. To book you need: party size, date, time, the guest's name, and a phone number or email. Zone and notes \
(allergies, occasion) are optional.
4. BEFORE calling create_booking, recap every detail (name, party size, weekday + date, time, zone, contact, notes) \
and ask the guest to confirm. Only call create_booking after the guest explicitly confirms in a later message - \neven if they gave every detail up front. Pass date as YYYY-MM-DD and time as HH:MM separately.
5. For changes or cancellations, get the booking code (EV-XXXX), call lookup_booking, then modify_booking or \
cancel_booking. A direct request to cancel a specific code counts as confirmation.
6. After a successful booking, give the booking code in bold and mention our 24-hour cancellation policy.
Never invent availability, tables or booking codes - only state what tools return. Speak in 12-hour times \
(8:00 pm). Keep replies short and elegant; use bold sparingly for key details.

Relevant restaurant information (cite as [n] only if you rely on it):
{docs}"""

RESPOND_SYSTEM = """You are the concierge of Ember & Vine, an upscale wood-fire restaurant and natural wine bar in \
San Francisco. Warm, elegant, concise.
{now}

Answer the guest's latest message using ONLY the restaurant information below. Cite the sources you use inline as \
[1], [2] matching the numbers. If the information doesn't cover the question, say so graciously and offer the host \
stand at (415) 555-0142. Keep it to 2-6 sentences or a short list. If natural, offer to reserve a table.

Restaurant information:
{docs}"""

SMALLTALK_SYSTEM = """You are the concierge of Ember & Vine, an upscale wood-fire restaurant and natural wine bar. \
{now} Reply briefly (1-2 sentences), warmly and with a little charm. Offer to help with a reservation or questions \
about the menu, allergens, hours, parking or events."""


# ====================================================================== nodes

async def router(state: AgentState) -> dict:
    writer = get_stream_writer()
    writer({"type": "node", "node": "router", "status": "start"})
    msgs = state["messages"]
    last = _last_human(msgs)
    intent: Optional[str] = None
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
            intent = None  # fall back to heuristics (e.g. model without forced tool_choice support)
    if intent not in ("info", "booking", "smalltalk"):
        intent = _heuristic_intent(last, msgs)
    writer({"type": "node", "node": "router", "status": "end", "intent": intent})
    return {"intent": intent, "tool_results": []}


async def retrieve(state: AgentState) -> dict:
    writer = get_stream_writer()
    writer({"type": "node", "node": "retrieve", "status": "start"})
    humans = [_text(m.content) for m in state["messages"] if isinstance(m, HumanMessage)]
    query = humans[-1] if humans else ""
    if len(query.split()) < 5 and len(humans) > 1:  # "yes please" -> add previous turn for context
        query = humans[-2] + " " + query
    docs = await asyncio.to_thread(rag.retrieve, query, 4)
    return {"retrieved_docs": docs}


async def booking_agent(state: AgentState) -> dict:
    writer = get_stream_writer()
    writer({"type": "node", "node": "booking_agent", "status": "start"})
    msgs = state["messages"]
    # collect tool results produced since the last human turn, and track the booking draft
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
    update: dict[str, Any] = {"tool_results": tool_results, "booking_draft": draft or None}

    if not LLM_ENABLED:
        update["messages"] = [_offline_booking(msgs, writer)]
        return update

    system = SystemMessage(content=BOOKING_SYSTEM.format(now=_now_context(),
                                                         docs=_format_docs(state.get("retrieved_docs") or [])))
    msg = await _llm(1500).bind_tools(TOOLS).ainvoke([system] + _sanitize(msgs))
    update["messages"] = [msg]
    return update


async def respond(state: AgentState) -> dict:
    writer = get_stream_writer()
    writer({"type": "node", "node": "respond", "status": "start"})
    intent = state.get("intent")
    if intent == "booking":
        return {}  # booking_agent already wrote (and streamed) the guest-facing reply, grounded in the same docs
    docs = state.get("retrieved_docs") or []
    if not LLM_ENABLED:
        if intent == "smalltalk":
            text = ("Good evening, and welcome to Ember & Vine. I'm your concierge - ask me about the menu, "
                    "allergens, hours or events, or let me check a table for you.")
        elif docs:
            top = docs[0]
            snippet = top["text"].split("\n\n", 1)[-1][:700].strip()
            text = (f"*(Offline demo mode - set ANTHROPIC_API_KEY for full answers.)* Here's the most relevant "
                    f"passage from our guide [1]:\n\n> {snippet.replace(chr(10), chr(10) + '> ')}")
        else:
            text = "I couldn't find that in our guide - please call the host stand at (415) 555-0142."
        _write_tokens(writer, text)
        return {"messages": [AIMessage(content=text)]}

    if intent == "smalltalk":
        system = SMALLTALK_SYSTEM.format(now=_now_context())
    else:
        system = RESPOND_SYSTEM.format(now=_now_context(), docs=_format_docs(docs))
    msg = await _llm(1200).ainvoke([SystemMessage(content=system)] + _text_history(state["messages"]))
    return {"messages": [AIMessage(content=_text(msg.content), id=msg.id)]}


# ====================================================================== offline booking (no API key)

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _offline_booking(msgs: list[AnyMessage], writer) -> AIMessage:
    last = msgs[-1]
    if isinstance(last, ToolMessage):
        results = []
        for m in reversed(msgs):
            if not isinstance(m, ToolMessage):
                break
            results.insert(0, json.loads(m.content))
        lines = []
        for r in results:
            if "error" in r:
                lines.append(f"Hmm - {r['error']}")
            elif "code" in r:
                lines.append(f"Booking **{r['code']}** for {r['guest_name']} ({r['party_size']} guests) on "
                             f"{r['start_time'].replace('T', ' at ')[:16]} at table {r['table_name']} is "
                             f"**{r['status']}**.")
            elif "available_times" in r:
                if r.get("requested_time"):
                    ok = r.get("requested_available")
                    lines.append(f"{r['requested_time']} on {r['date']} for {r['party_size']} is "
                                 f"{'**available**' if ok else 'taken'}." +
                                 ("" if ok else f" Nearest options: {', '.join(r.get('nearest_alternatives') or []) or 'none'}."))
                else:
                    lines.append(f"Open times on {r['date']} for {r['party_size']}: "
                                 f"{', '.join(r['available_times']) or 'none'}.")
        lines.append("\n*(Offline demo mode: I can check availability, look up and cancel bookings. "
                     "Use the booking panel to reserve, or set ANTHROPIC_API_KEY for the full concierge.)*")
        text = "\n".join(lines)
        _write_tokens(writer, text)
        return AIMessage(content=text)

    text = _last_human(msgs)
    low = text.lower()
    code = re.search(r"\bEV-[A-Z0-9]{4}\b", text.upper())
    call: Optional[dict] = None
    if code and "cancel" in low:
        call = {"name": "cancel_booking", "args": {"code": code.group(0)}}
    elif code:
        call = {"name": "lookup_booking", "args": {"code": code.group(0)}}
    else:
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
        party = re.search(r"(?:for|party of|table for)\s+(\d{1,2})|(\d{1,2})\s*(?:people|guests|persons|pax)", low)
        size = int(next(g for g in party.groups() if g)) if party else 2
        tm = re.search(r"(?:at|@)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?|(\d{1,2})(?::(\d{2}))?\s*(am|pm)", low)
        args: dict[str, Any] = {"date": day.isoformat(), "party_size": size}
        if tm:
            h, mnt, ap = (tm.group(1), tm.group(2), tm.group(3)) if tm.group(1) else (tm.group(4), tm.group(5), tm.group(6))
            hour = int(h)
            if ap == "am" and hour == 12:
                hour = 0
            elif ap != "am" and hour < 12:  # pm, or no suffix: dinner times mean pm
                hour += 12
            args["time"] = f"{hour:02d}:{mnt or '00'}"
        zone = next((z for z in bs.ZONES if z in low), None)
        if zone:
            args["zone"] = zone
        call = {"name": "check_availability", "args": args}
    return AIMessage(content="", tool_calls=[{**call, "id": f"offline_{uuid.uuid4().hex[:10]}", "type": "tool_call"}])


# ====================================================================== graph

def _after_router(state: AgentState) -> str:
    return "respond" if state.get("intent") == "smalltalk" else "retrieve"


def _after_retrieve(state: AgentState) -> str:
    return "booking_agent" if state.get("intent") == "booking" else "respond"


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
    g.add_edge(START, "router")
    g.add_conditional_edges("router", _after_router, ["retrieve", "respond"])
    g.add_conditional_edges("retrieve", _after_retrieve, ["booking_agent", "respond"])
    g.add_conditional_edges("booking_agent", _after_agent, ["tools", "respond"])
    g.add_edge("tools", "booking_agent")
    g.add_edge("respond", END)
    return g.compile(checkpointer=MemorySaver())


GRAPH = build_graph()


async def run_chat(message: str, thread_id: str) -> AsyncIterator[dict]:
    """Run one guest turn and yield UI events."""
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 30}
    inputs = {"messages": [HumanMessage(content=message)], "intent": "", "retrieved_docs": [], "tool_results": []}
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
        full = "".join(streamed)
        if intent == "info":
            sources = docs
        else:  # booking: only chips for docs the agent actually cited
            sources = [d for d in docs if f"[{d['index']}]" in full]
        if sources:
            yield {"type": "sources", "sources": sources}
    except Exception as e:  # surface errors to the UI instead of a dead stream
        yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
    yield {"type": "done"}

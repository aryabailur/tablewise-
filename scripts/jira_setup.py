"""One-shot Jira setup for Tablewise: 5 epics, child stories (bulk), and a sprint on the TAB board.

Usage:  JIRA_API_TOKEN='...' python scripts/jira_setup.py
The token is only read from the environment and is never written anywhere.
Idempotent: issues are matched by exact summary and the sprint by name, so re-running won't duplicate.
Created keys are saved to scripts/jira_issues.json (gitignored).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = os.getenv("JIRA_BASE_URL", "https://aryabailur.atlassian.net").rstrip("/")
EMAIL = os.getenv("JIRA_EMAIL", "aryabailur@gmail.com")
TOKEN = os.getenv("JIRA_API_TOKEN")
PROJECT = os.getenv("JIRA_PROJECT_KEY", "TAB")
BOARD = int(os.getenv("JIRA_BOARD_ID", "69"))
OUT = Path(__file__).with_name("jira_issues.json")

SPRINT_NAME = "TAB Sprint 1 - MVP"  # Jira caps sprint names at 30 chars
SPRINT_GOAL = ("Ship the Tablewise MVP: booking engine, RAG knowledge base, LangGraph + MCP concierge "
               "and cinematic UI.")
LABEL = "tablewise"

EPICS = [
    ("Booking Engine", "Tables, availability, booking lifecycle and the REST API (backend/app/booking_service.py)."),
    ("RAG & Knowledge Base", "Ember & Vine knowledge docs, chunking, fastembed embeddings and ChromaDB retrieval."),
    ("AI Concierge (LangGraph + MCP)", "LangGraph agent, SSE streaming, LLM provider and the MCP server."),
    ("Frontend & UI", "Vite + React + Tailwind + Framer Motion guest experience, concierge drawer and admin view."),
    ("DevOps, Docs & QA", "Dev tooling, documentation, CI, repo hygiene and test coverage."),
]

# (epic index, summary, description, shipped?)  shipped -> Done + in the sprint; otherwise backlog
STORIES = [
    (0, "Data model for tables and bookings (SQLModel + SQLite)",
     "Table and Booking models; 14 seeded tables across window, garden, bar and private zones.", True),
    (0, "Availability engine with 30-minute slots and smallest-fit table",
     "Seatings 17:00-22:00, 90-minute holds, parties 1-12, no overlapping confirmed bookings.", True),
    (0, "Booking lifecycle with EV-XXXX codes",
     "Create, modify, cancel and look up bookings by human-readable code.", True),
    (0, "REST API for availability, bookings, tables and health",
     "FastAPI routes under /api with guest-safe 4xx errors.", True),
    (0, "Fix naive datetime rejection in sqlmodel 0.0.48",
     "Pinned datetime columns to a naive SQLAlchemy DateTime so bookings and availability work.", True),
    (1, "Write the Ember & Vine knowledge base",
     "menu, allergens, policies, hours & location, events and FAQ markdown docs.", True),
    (1, "Heading-aware chunking with source metadata",
     "~400 token chunks with 50 token overlap; metadata stores source file and section title.", True),
    (1, "Idempotent ChromaDB ingest and retrieval with fastembed",
     "BAAI/bge-small-en-v1.5 embeddings, persistent Chroma at backend/data/chroma, retrieve(query, k=4).", True),
    (1, "Cite sources in concierge answers",
     "Answers cite [n] sources, streamed to the UI as expandable source chips.", True),
    (2, "LangGraph agent: router, retrieve, booking_agent, tools, respond",
     "StateGraph with structured-output intent routing and a MemorySaver checkpointer keyed by thread_id.", True),
    (2, "Stream graph events to the UI over SSE",
     "node, token, tool, sources, booking, error and done events from POST /api/chat.", True),
    (2, "Confirm-before-booking guardrail and relative dates",
     "Agent recaps details and waits for an explicit yes; server date injected for 'tomorrow at 8'.", True),
    (2, "Switch LLM provider to Groq (openai/gpt-oss-120b)",
     "LLM_PROVIDER=groq by default; Anthropic remains selectable. Offline demo mode without a key.", True),
    (2, "MCP server exposing booking and search tools",
     "FastMCP/MCPServer over stdio reusing booking_service and rag directly; works with mcp 1.x and 2.x.", True),
    (3, "Cinematic theme: gradient mesh, cursor orbs, grain and glass cards",
     "Late-night fine dining look with Fraunces + Inter, animated hero and magnetic CTA.", True),
    (3, "Booking panel with date strip, party dial, slot pills and ticket",
     "Live availability, table chips, guest form, ticket-style confirmation with confetti.", True),
    (3, "Concierge drawer with streaming chat, graph trace and tool cards",
     "Ctrl/Cmd+K drawer, live node trace, tool call cards, source chips and in-chat tickets.", True),
    (3, "Admin timeline and dark/light theme",
     "Day timeline of bookings by table with stats and cancel; parchment light theme.", True),
    (3, "Interactive SVG floor plan",
     "Cut from the MVP: replace table chips with a clickable floor plan that lights up free tables.", False),
    (3, "Show open times in the availability tool card",
     "Tool card summary doesn't read the check_availability result shape (available_times).", False),
    (4, "README, architecture diagrams and dev runner",
     "Mermaid diagrams, MCP config snippet, Makefile and cross-platform scripts/dev.py.", True),
    (4, "Repo hygiene, MIT license and CI",
     "gitignore for secrets and runtime data, secret scan, GitHub Actions build + import smoke test.", True),
    (4, "Automated tests for booking service and agent graph", "pytest coverage for availability, "
     "overlaps, booking lifecycle and graph routing.", False),
    (4, "Protect the admin view", "Admin timeline currently has no authentication.", False),
    (4, "Code-split the frontend bundle", "Single 553 kB bundle triggers Vite's chunk-size warning.", False),
]


session = requests.Session()
session.auth = (EMAIL, TOKEN or "")
session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})


def call(method: str, path: str, **kwargs):
    r = session.request(method, BASE + path, timeout=30, **kwargs)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:600]}")
    return r.json() if r.text.strip() else {}


def adf(text: str) -> dict:
    return {"type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def existing_issues() -> dict[str, dict]:
    found, token = {}, None
    while True:
        body = {"jql": f"project = {PROJECT}", "fields": ["summary", "status"], "maxResults": 100}
        if token:
            body["nextPageToken"] = token
        data = call("POST", "/rest/api/3/search/jql", json=body)
        for issue in data.get("issues", []):
            status = issue["fields"].get("status") or {}
            found[issue["fields"]["summary"]] = {
                "key": issue["key"], "done": (status.get("statusCategory") or {}).get("key") == "done"}
        token = data.get("nextPageToken")
        if not token:
            return found


def issue_type_ids() -> tuple[str, str]:
    project = call("GET", f"/rest/api/3/project/{PROJECT}")
    types = {t["name"].lower(): t["id"] for t in project.get("issueTypes", []) if not t.get("subtask")}
    epic, story = types.get("epic"), types.get("story") or types.get("task")
    if not epic or not story:
        raise RuntimeError(f"{PROJECT} needs Epic and Story/Task issue types, found: {sorted(types)}")
    return epic, story


def bulk_create(fields_list: list[dict]) -> list[str | None]:
    """POST /issue/bulk in chunks of 50; returns keys aligned with the input (None where creation failed)."""
    keys: list[str | None] = [None] * len(fields_list)
    for start in range(0, len(fields_list), 50):
        chunk = fields_list[start:start + 50]
        data = call("POST", "/rest/api/3/issue/bulk", json={"issueUpdates": [{"fields": f} for f in chunk]})
        failed = {e["failedElementNumber"] for e in data.get("errors", [])}
        for e in data.get("errors", []):
            print(f"  ! failed: {chunk[e['failedElementNumber']]['summary']}: {e.get('elementErrors')}")
        created = iter(data.get("issues", []))
        for i in range(len(chunk)):
            if i not in failed:
                keys[start + i] = next(created)["key"]
    return keys


def transition_to_done(key: str) -> bool:
    transitions = call("GET", f"/rest/api/3/issue/{key}/transitions").get("transitions", [])
    done = next((t for t in transitions
                 if ((t.get("to") or {}).get("statusCategory") or {}).get("key") == "done"), None)
    if not done:
        return False
    call("POST", f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": done["id"]}})
    return True


def ensure_sprint(now: datetime) -> dict:
    for sprint in call("GET", f"/rest/agile/1.0/board/{BOARD}/sprint?state=active,future").get("values", []):
        if sprint["name"] == SPRINT_NAME:
            return sprint
    return call("POST", "/rest/agile/1.0/sprint", json={
        "name": SPRINT_NAME, "originBoardId": BOARD, "goal": SPRINT_GOAL,
        "startDate": iso(now), "endDate": iso(now + timedelta(days=14))})


def main() -> int:
    if not TOKEN:
        print("Set JIRA_API_TOKEN in the environment.", file=sys.stderr)
        return 1
    epic_type, story_type = issue_type_ids()
    existing = existing_issues()
    base = {"project": {"key": PROJECT}, "labels": [LABEL]}

    # 1) epics
    new_epics = [(name, desc) for name, desc in EPICS if name not in existing]
    keys = bulk_create([{**base, "issuetype": {"id": epic_type}, "summary": n, "description": adf(d)}
                        for n, d in new_epics])
    for (name, _), key in zip(new_epics, keys):
        if key:
            existing[name] = {"key": key, "done": False}
    epic_keys = [existing.get(name, {}).get("key") for name, _ in EPICS]

    # 2) stories under their epics
    new_stories = [s for s in STORIES if s[1] not in existing and epic_keys[s[0]]]
    keys = bulk_create([{**base, "issuetype": {"id": story_type}, "summary": s[1], "description": adf(s[2]),
                         "parent": {"key": epic_keys[s[0]]}} for s in new_stories])
    for story, key in zip(new_stories, keys):
        if key:
            existing[story[1]] = {"key": key, "done": False}

    # 3) sprint with the shipped stories
    now = datetime.now(timezone.utc)
    shipped = [existing[s[1]]["key"] for s in STORIES if s[3] and s[1] in existing]
    sprint, sprint_note = None, ""
    try:
        sprint = ensure_sprint(now)
        for start in range(0, len(shipped), 50):
            call("POST", f"/rest/agile/1.0/sprint/{sprint['id']}/issue", json={"issues": shipped[start:start + 50]})
        if sprint.get("state") == "future":
            try:
                call("POST", f"/rest/agile/1.0/sprint/{sprint['id']}", json={
                    "state": "active", "startDate": iso(now), "endDate": iso(now + timedelta(days=14))})
                sprint["state"] = "active"
            except RuntimeError as e:
                sprint_note = f"created but not started ({e})"
    except RuntimeError as e:
        sprint_note = f"sprint step skipped: {e}"

    # 4) mark shipped stories Done
    moved = 0
    for s in STORIES:
        info = existing.get(s[1])
        if s[3] and info and not info["done"]:
            try:
                if transition_to_done(info["key"]):
                    info["done"] = True
                    moved += 1
            except RuntimeError as e:
                print(f"  ! could not transition {info['key']}: {e}")

    result = {
        "epics": {name: existing.get(name, {}).get("key") for name, _ in EPICS},
        "stories": [{"key": existing.get(s[1], {}).get("key"), "summary": s[1], "epic": EPICS[s[0]][0],
                     "done": existing.get(s[1], {}).get("done", False)} for s in STORIES],
        "sprint": {"id": sprint.get("id"), "name": sprint.get("name"), "state": sprint.get("state")} if sprint else None,
    }
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Epics:   {', '.join(f'{k} {n}' for n, k in result['epics'].items())}")
    print(f"Stories: {sum(1 for s in result['stories'] if s['key'])}/{len(STORIES)} "
          f"({sum(1 for s in result['stories'] if s['done'])} Done, {moved} transitioned this run)")
    if sprint:
        print(f"Sprint:  {sprint['name']} (id {sprint['id']}, {sprint.get('state')}) with {len(shipped)} shipped stories")
    if sprint_note:
        print(f"Note:    {sprint_note}")
    print(f"Board:   {BASE}/jira/software/projects/{PROJECT}/boards/{BOARD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

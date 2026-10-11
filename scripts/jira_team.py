"""Two-person team setup for Jira project TAB: names epics and sprints, adds Sprint 2 and new stories,
assigns owners and adds watchers. Run after scripts/jira_setup.py.

Usage:  JIRA_API_TOKEN='...' python scripts/jira_team.py
The token is only read from the environment. Idempotent: stories are matched by summary, sprints by name.
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

PEOPLE = {"arya": "aryabailur@gmail.com", "irisha": "irishaa1404@gmail.com"}
EPIC_OWNERS = {"TAB-1": "arya", "TAB-2": "arya", "TAB-3": "arya", "TAB-4": "irisha", "TAB-5": "irisha"}
EPIC_NAMES = {"TAB-4": "Frontend & Google Maps Page", "TAB-5": "DevOps & Docs"}
SPRINT1, SPRINT2 = "MVP Build", "Hardening & Launch"

# Existing backlog stories that move to Sprint 2, with an owner override (tests, admin auth -> Arya)
SPRINT2_EXISTING = {"TAB-28": "arya", "TAB-29": "arya"}

# (summary, epic, owner, sprint, description)  sprint 1 = current work (feature-branch PRs), 2 = next sprint
NEW_STORIES = [
    ("Validate booking API input", "TAB-1", "arya", 1,
     "Reject malformed guest names, phones, emails, zones and start times on the booking endpoints with 422s."),
    ("Guardrail node for off-topic requests", "TAB-3", "arya", 1,
     "LangGraph guardrail node that politely declines requests unrelated to the restaurant, without tool calls."),
    ("Loading skeletons in the booking panel", "TAB-4", "irisha", 1,
     "Skeleton placeholders for time slots and tables while availability loads."),
    ("Mobile polish for the booking panel", "TAB-4", "irisha", 1,
     "Tighter spacing, touch targets and scrolling for the booking panel on small screens."),
    ("Jenkins stage for frontend lint", "TAB-5", "irisha", 1,
     "ESLint for the frontend and a Frontend: Lint stage in the Jenkinsfile."),
    ("Booking confirmation notifications", "TAB-1", "arya", 2,
     "Email/SMS confirmation and reminder when a booking is created, changed or cancelled."),
    ("Deploy Tablewise (API + frontend)", "TAB-5", "irisha", 2,
     "Deploy the FastAPI backend and Vite frontend with environment-based secrets."),
    ("Spike: Reserve with Google", "TAB-4", "irisha", 2,
     "Investigate Reserve with Google / Google Maps booking integration requirements and effort."),
]

session = requests.Session()
session.auth = (EMAIL, TOKEN or "")
session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})


def call(method: str, path: str, **kwargs):
    r = session.request(method, BASE + path, timeout=30, **kwargs)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
    return r.json() if r.text.strip() else {}


def adf(text: str) -> dict:
    return {"type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def all_issues() -> dict[str, dict]:
    """key -> {summary, type, parent}"""
    found, token = {}, None
    while True:
        body = {"jql": f"project = {PROJECT} ORDER BY key", "fields": ["summary", "issuetype", "parent"],
                "maxResults": 100}
        if token:
            body["nextPageToken"] = token
        data = call("POST", "/rest/api/3/search/jql", json=body)
        for i in data.get("issues", []):
            f = i["fields"]
            found[i["key"]] = {"summary": f["summary"], "type": f["issuetype"]["name"],
                               "parent": (f.get("parent") or {}).get("key")}
        token = data.get("nextPageToken")
        if not token:
            return found


def account_id(email: str) -> str | None:
    users = call("GET", "/rest/api/3/user/search", params={"query": email})
    return next((u["accountId"] for u in users if u.get("accountType") == "atlassian"), None)


def sprint_by_name(name: str) -> dict | None:
    data = call("GET", f"/rest/agile/1.0/board/{BOARD}/sprint", params={"state": "active,future", "maxResults": 50})
    return next((s for s in data.get("values", []) if s["name"] == name), None)


def main() -> int:
    if not TOKEN:
        print("Set JIRA_API_TOKEN in the environment.", file=sys.stderr)
        return 1
    notes: list[str] = []
    ids = {who: account_id(mail) for who, mail in PEOPLE.items()}
    for who, acc in ids.items():
        print(f"{'OK ' if acc else 'MISSING'} Jira account for {PEOPLE[who]}: {acc or 'not found'}")
    if not ids["irisha"]:
        notes.append("Irisha (irishaa1404@gmail.com) has no Jira account on this site yet - invite her and grant "
                     "TAB project access, then re-run this script to assign her issues.")

    # epic names
    issues = all_issues()
    for key, name in EPIC_NAMES.items():
        if issues.get(key, {}).get("summary") != name:
            call("PUT", f"/rest/api/3/issue/{key}", json={"fields": {"summary": name}})
            print(f"renamed {key} -> {name}")

    # sprints: rename the active MVP sprint, create Sprint 2
    now = datetime.now(timezone.utc)
    s1 = sprint_by_name(SPRINT1)
    if not s1:
        active = call("GET", f"/rest/agile/1.0/board/{BOARD}/sprint", params={"state": "active"}).get("values", [])
        if active:
            s1 = call("POST", f"/rest/agile/1.0/sprint/{active[0]['id']}", json={"name": SPRINT1})
            print(f"renamed sprint {active[0]['name']!r} -> {SPRINT1!r}")
        else:
            s1 = call("POST", "/rest/agile/1.0/sprint", json={"name": SPRINT1, "originBoardId": BOARD,
                                                               "startDate": iso(now), "endDate": iso(now + timedelta(days=14))})
    s2 = sprint_by_name(SPRINT2)
    if not s2:
        s1_end = datetime.fromisoformat((s1.get("endDate") or iso(now + timedelta(days=14))).replace("Z", "+00:00"))
        s2 = call("POST", "/rest/agile/1.0/sprint", json={
            "name": SPRINT2, "originBoardId": BOARD, "goal": "Tests, admin auth, notifications, deploy, Reserve with Google",
            "startDate": iso(s1_end), "endDate": iso(s1_end + timedelta(days=14))})
        print(f"created sprint {SPRINT2!r}")

    # new stories (bulk)
    by_summary = {v["summary"]: k for k, v in issues.items()}
    types = {t["name"].lower(): t["id"] for t in call("GET", f"/rest/api/3/project/{PROJECT}")["issueTypes"]}
    story_type = types.get("story") or types.get("task")
    todo = [s for s in NEW_STORIES if s[0] not in by_summary]
    if todo:
        res = call("POST", "/rest/api/3/issue/bulk", json={"issueUpdates": [{"fields": {
            "project": {"key": PROJECT}, "issuetype": {"id": story_type}, "summary": s[0], "description": adf(s[4]),
            "labels": ["tablewise"], "parent": {"key": s[1]}}} for s in todo]})
        failed = {e["failedElementNumber"] for e in res.get("errors", [])}
        created = iter(res.get("issues", []))
        for i, s in enumerate(todo):
            if i not in failed:
                by_summary[s[0]] = next(created)["key"]
        for e in res.get("errors", []):
            notes.append(f"could not create {todo[e['failedElementNumber']][0]!r}: {e.get('elementErrors')}")
        issues = all_issues()

    # sprint membership
    sprint_keys = {1: [], 2: list(SPRINT2_EXISTING)}
    for s in NEW_STORIES:
        if s[0] in by_summary:
            sprint_keys[s[3]].append(by_summary[s[0]])
    for num, sprint in ((1, s1), (2, s2)):
        if sprint_keys[num]:
            call("POST", f"/rest/agile/1.0/sprint/{sprint['id']}/issue", json={"issues": sprint_keys[num]})

    # owners: by epic, then explicit overrides
    owners: dict[str, str] = {}
    for key, info in issues.items():
        epic = key if info["type"].lower() == "epic" else info["parent"]
        if epic in EPIC_OWNERS:
            owners[key] = EPIC_OWNERS[epic]
    owners.update(SPRINT2_EXISTING)
    owners.update({by_summary[s[0]]: s[2] for s in NEW_STORIES if s[0] in by_summary})

    assigned = {"arya": [], "irisha": []}
    for key, who in sorted(owners.items(), key=lambda kv: int(kv[0].split("-")[1])):
        if not ids[who]:
            continue
        try:
            call("PUT", f"/rest/api/3/issue/{key}/assignee", json={"accountId": ids[who]})
            assigned[who].append(key)
        except RuntimeError as e:
            notes.append(f"could not assign {key} to {who}: {e}")

    # watchers on own epics
    for epic, who in EPIC_OWNERS.items():
        if ids[who]:
            try:
                call("POST", f"/rest/api/3/issue/{epic}/watchers", data=json.dumps(ids[who]))
            except RuntimeError as e:
                notes.append(f"could not add {who} as watcher on {epic}: {e}")

    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    data["team"] = {"account_ids": ids, "assigned": assigned,
                    "new_stories": {s[0]: by_summary.get(s[0]) for s in NEW_STORIES},
                    "sprints": {SPRINT1: s1.get("id"), SPRINT2: s2.get("id")},
                    "sprint2_keys": sprint_keys[2]}
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")

    print("New stories: " + ", ".join(f"{by_summary.get(s[0])} {s[0]} ({s[2]}, sprint {s[3]})" for s in NEW_STORIES))
    print(f"Sprints: {SPRINT1} (id {s1.get('id')}), {SPRINT2} (id {s2.get('id')}) <- {', '.join(sprint_keys[2])}")
    for who, keys in assigned.items():
        print(f"Assigned to {who}: {len(keys)} issues {keys[:3]}{'...' if len(keys) > 3 else ''}")
    for n in notes:
        print(f"NOTE: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

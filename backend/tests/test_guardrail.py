"""The guardrail node short-circuits off-topic requests: router -> guardrail, no retrieval, no tools, no LLM."""
from __future__ import annotations

import asyncio

from app import graph


def _run(message: str, thread_id: str) -> list[dict]:
    async def collect():
        return [event async for event in graph.run_chat(message, thread_id)]
    return asyncio.run(collect())


def test_guardrail_declines_off_topic_requests(monkeypatch):
    monkeypatch.setattr(graph, "LLM_ENABLED", False)  # heuristic router, no network
    events = _run("Write me a Python script that scrapes stock prices", "test-offtopic")

    started = [e["node"] for e in events if e["type"] == "node" and e.get("status") == "start"]
    assert started == ["router", "guardrail"]
    assert any(e.get("intent") == "offtopic" for e in events if e["type"] == "node")
    assert "Tablewise" in "".join(e["content"] for e in events if e["type"] == "token")
    assert not [e for e in events if e["type"] in ("tool", "sources", "error")]
    assert events[-1] == {"type": "done"}


def test_restaurant_questions_are_not_flagged_off_topic():
    assert graph._heuristic_intent("Is the wine list good with the menu?", []) == "info"
    assert graph._heuristic_intent("Book a table for 2 tomorrow at 7pm", []) == "booking"


def test_discover_intent_and_restaurant_mentions():
    assert graph._heuristic_intent("Any rooftop places in Bandra for Saturday?", []) == "discover"
    assert graph._heuristic_intent("Rooftop table for 4 in Bandra tomorrow at 8pm?", []) == "discover"
    assert graph._heuristic_intent("Table for 2 tomorrow at 8pm", []) == "booking"
    assert graph._heuristic_intent("Does Trattoria Alba have vegan pizza?", []) == "info"
    assert graph.mentioned_restaurants("Is Koli & Tide or kanji better?") == ["koli-tide", "kanji-house"]
    assert graph.resolve_restaurant("Tulsi Thali House") == "tulsi-thali"

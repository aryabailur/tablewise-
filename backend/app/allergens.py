"""Allergy cross-check: read a restaurant's knowledge/<slug>/menu.md and list the dishes a guest should avoid.

Each menu line looks like ``- **Dish** - description. Price. (V, GF) Contains: dairy, tree nuts.`` A dish is flagged
when any keyword for the allergen appears anywhere on its line (the "Contains:" clause or the description), so the
check errs on the side of caution. No database, LLM or vector index is needed.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
ALLERGENS = ("nuts", "peanuts", "gluten", "dairy", "shellfish", "fish", "eggs", "soy", "sesame")
LABELS = {"nuts": "tree-nut", "peanuts": "peanut", "gluten": "gluten", "dairy": "dairy", "shellfish": "shellfish",
          "fish": "fish", "eggs": "egg", "soy": "soy", "sesame": "sesame"}
_KEYWORDS = {
    "nuts": r"tree nuts?|\bnuts?\b|almond|hazelnut|pistachio|cashew|walnut|pecan|macadamia|praline",
    "peanuts": r"peanut|groundnut",
    "gluten": r"gluten|wheat|semolina|\brava\b|barley|\brye\b",
    "dairy": r"dairy|\bmilk|cream|cheese|butter\b|\bghee\b|yoghurt|yogurt|paneer|\bcurd|khoya|malai",
    "shellfish": r"shellfish|mollusc|prawn|shrimp|crab|lobster|clam|oyster|scallop|squid|octopus|mussel",
    "fish": r"\bfish\b|anchov|bonito|dashi|tuna|salmon",
    "eggs": r"\beggs?\b|mayo",
    "soy": r"\bsoy|tofu|\bmiso\b|edamame|tamari",
    "sesame": r"sesame|tahini",
}
_PATTERNS = {a: re.compile(p, re.IGNORECASE) for a, p in _KEYWORDS.items()}
_DISH = re.compile(r"^\s*[-*]\s+\*\*(.+?)\*\*(.*)$")


@lru_cache(maxsize=32)
def _menu(slug: str, knowledge_dir: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    """(restaurant name from the H1, ((dish, full line), ...)) for a restaurant's menu.md; empty if missing."""
    path = Path(knowledge_dir) / slug / "menu.md"
    if not path.is_file():
        return slug, ()
    name, dishes = slug, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ") and name == slug:
            name = re.split(r"\s+[—–-]\s+", line[2:].strip(), maxsplit=1)[0]
        m = _DISH.match(line)
        if m:
            dishes.append((m.group(1).strip(), line))
    return name, tuple(dishes)


def dishes_to_avoid(restaurant_slug: str, allergies: list[str] | None,
                    knowledge_dir: Path = KNOWLEDGE_DIR) -> dict[str, list[str]]:
    """{allergy: [dish names on this restaurant's menu that contain it]} for each known allergy."""
    _, dishes = _menu(restaurant_slug, str(knowledge_dir))
    out: dict[str, list[str]] = {}
    for allergy in allergies or []:
        pattern = _PATTERNS.get(allergy)
        if pattern:
            out[allergy] = [dish for dish, line in dishes if pattern.search(line)]
    return out


def allergy_check(restaurant_slug: str, allergies: list[str] | None,
                  knowledge_dir: Path = KNOWLEDGE_DIR) -> dict[str, Any] | None:
    """Structured cross-check plus a guest-facing note; None when there are no allergies."""
    allergies = [a for a in (allergies or []) if a in _PATTERNS]
    if not allergies:
        return None
    name, dishes = _menu(restaurant_slug, str(knowledge_dir))
    avoid = dishes_to_avoid(restaurant_slug, allergies, knowledge_dir)
    if not dishes:
        note = (f"I couldn't find a menu for {name} to check against, so please flag your "
                f"{', '.join(LABELS[a] for a in allergies)} allergy to your server on arrival.")
    else:
        parts = []
        for a in allergies:
            hits = avoid.get(a) or []
            parts.append(f"with a {LABELS[a]} allergy, avoid {_join(hits)}" if hits
                         else f"no dish lists {LABELS[a]}, but traces are possible")
        note = (f"**Allergy check ({name} menu):** {'; '.join(parts)}. The kitchen handles all major allergens, "
                "so please remind your server on arrival.")
    return {"allergies": allergies, "avoid": avoid, "source": f"{restaurant_slug}/menu.md", "note": note}


def attach_allergy_check(booking: dict[str, Any]) -> dict[str, Any]:
    """Add ``allergy_check`` to a booking dict (from booking_service) when it lists allergies; errors pass through."""
    if isinstance(booking, dict) and "error" not in booking and booking.get("allergies"):
        booking["allergy_check"] = allergy_check(booking.get("restaurant_slug") or "", booking["allergies"])
    return booking


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]

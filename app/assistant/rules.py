from __future__ import annotations

import json
import re
from typing import Any


_RU_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+", re.UNICODE)


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def route_quiz_category(answers: dict[str, Any]) -> str:
    """
    Deterministic fallback classifier for /assistant/route-quiz.
    Must return one of: IT, искусство, история
    """
    raw = json.dumps(answers or {}, ensure_ascii=False)
    t = _norm(raw)
    # IT
    if any(k in t for k in ("it", "айти", "программ", "код", "python", "java", "js", "backend", "frontend", "хакатон")):
        return "IT"
    # Art
    if any(
        k in t
        for k in (
            "выстав",
            "музе",
            "галере",
            "театр",
            "концерт",
            "кино",
            "арт",
            "фестив",
            "музык",
            "танц",
        )
    ):
        return "искусство"
    # History
    if any(k in t for k in ("истор", "экскурс", "памятник", "архив", "краевед", "усадьб", "музей истории")):
        return "история"
    return "история"


def extract_keywords(text: str, *, limit: int = 6) -> list[str]:
    tokens = [w.lower() for w in _RU_WORD_RE.findall(text or "")]
    out: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        if len(t) < 3:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= limit:
            break
    return out


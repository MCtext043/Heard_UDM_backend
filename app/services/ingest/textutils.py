from __future__ import annotations

import re
from html import unescape


def strip_html(text: str | None, max_len: int = 8000) -> str:
    if not text:
        return ""
    t = unescape(re.sub(r"<[^>]+>", " ", str(text)))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len]

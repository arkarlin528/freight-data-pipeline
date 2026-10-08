"""
Reference data shared with the logistics platform (project #1): its port codes (UN/LOCODE),
carrier codes and container types. A rate the platform can't accept is rejected here, early,
with a clear reason, instead of bouncing back from the import API.
"""

from __future__ import annotations

import re

PORTS: dict[str, tuple[str, ...]] = {
    # code: names and spellings seen on carrier sites
    "THLCH": ("laem chabang", "laemchabang", "lcb"),
    "THBKK": ("bangkok", "bkk", "khlong toei"),
    "SGSIN": ("singapore",),
    "MYPKG": ("port klang", "klang", "port kelang"),
    "VNSGN": ("ho chi minh city", "ho chi minh", "saigon", "hcmc", "cat lai"),
    "IDJKT": ("jakarta", "tanjung priok"),
    "MMRGN": ("yangon", "rangoon"),
    "CNSHA": ("shanghai",),
    "HKHKG": ("hong kong",),
    "JPTYO": ("tokyo",),
    "NLRTM": ("rotterdam",),
    "USLAX": ("los angeles", "la"),
}

CARRIERS = {"ASL", "MCL", "SSC"}
CONTAINER_TYPES = {"20GP", "40GP", "40HC"}

_NAME_TO_CODE = {name: code for code, names in PORTS.items() for name in names}


def port_code(text: str) -> str | None:
    """'Laem Chabang, Thailand' → 'THLCH'; 'thlch' → 'THLCH'; unknown → None."""
    cleaned = text.strip()
    if re.fullmatch(r"[A-Za-z]{5}", cleaned) and cleaned.upper() in PORTS:
        return cleaned.upper()
    name = cleaned.split(",")[0].strip().lower()
    return _NAME_TO_CODE.get(name)


_CONTAINER_PATTERNS = [
    (re.compile(r"^20\W*(gp|dv|dc|st|std|standard)?$"), "20GP"),
    (re.compile(r"^40\W*(gp|dv|dc|st|std|standard)$"), "40GP"),
    (re.compile(r"^40\W*(hc|hq|high\s*cube)$"), "40HC"),
]


def container_type(text: str) -> str | None:
    """'40' High Cube', "40'HC", '40hq', '20GP' → canonical code; anything else (e.g. 45'HC) → None."""
    cleaned = re.sub(r"\s+", " ", text.strip().lower().replace("'", " ").replace("’", " ")).replace(" ", "")  # noqa: RUF001 (curly quotes occur in carrier data)
    cleaned = cleaned.replace("highcube", "hc")
    for pattern, code in _CONTAINER_PATTERNS:
        if pattern.match(cleaned):
            return code
    return None

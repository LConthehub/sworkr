"""
Contacts (called clients in the database and the API): who they are and what they're shown as.

A contact may have a name, social media handles, or both; sometimes a handle is all that's known.
Their `display_name` is what sworkr shows everywhere: their name, or the handle chosen to show them by
(and the first handle when there's no name).
"""

import json
import re
from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel

MAX_HANDLES = 12

# Suggestions for the platform box; anything else may be typed.
PLATFORMS = ["Instagram", "X (Twitter)", "OF", "Fansly", "TikTok", "Snapchat", "Telegram", "WhatsApp", "Signal",
             "Reddit", "Discord", "Bluesky", "Facebook", "LinkedIn", "Tryst", "Eros", "Other"]


class Handle(BaseModel):
    platform: Optional[str] = None
    handle: str


def clean_handles(handles: List[Handle]) -> List[dict]:
    out = []
    for h in handles:
        handle = (h.handle or "").strip()
        platform = (h.platform or "").strip() or None
        if not handle:
            continue
        if len(handle) > 200 or (platform and len(platform) > 60):
            raise HTTPException(status_code=400, detail="That handle is too long")
        out.append({"platform": platform, "handle": handle})
    if len(out) > MAX_HANDLES:
        raise HTTPException(status_code=400, detail=f"At most {MAX_HANDLES} handles")
    return out


def handle_label(h: dict) -> str:
    """'@sunny_days (Instagram)'. Handles that are links or phone numbers are shown as typed."""
    handle = h["handle"]
    if not handle.startswith("@") and re.fullmatch(r"[\w.\-]+", handle):
        handle = "@" + handle
    return f"{handle} ({h['platform']})" if h.get("platform") else handle


def display_name(name: Optional[str], handles: List[dict], display_handle: Optional[int]) -> str:
    """What the contact is shown as. Raises 400 when there's nothing to show them by."""
    name = (name or "").strip()
    if display_handle is not None and not (0 <= display_handle < len(handles)):
        display_handle = None
    if display_handle is not None:
        return handle_label(handles[display_handle])
    if name:
        return name
    if handles:
        return handle_label(handles[0])
    raise HTTPException(status_code=400, detail="Give a name or at least one social media handle")


def handles_json(handles: List[dict]) -> Optional[str]:
    return json.dumps(handles) if handles else None


def handles_from_db(value: Optional[str]) -> List[dict]:
    try:
        return json.loads(value) if value else []
    except ValueError:
        return []


def parse_handles_text(text: str) -> List[dict]:
    """'Instagram: @sunny; X: sunny_x; @plain' → handles (used by CSV import)."""
    out = []
    for part in re.split(r"[;\n]", text or ""):
        part = part.strip()
        if not part:
            continue
        platform, sep, handle = part.partition(":")
        if sep and handle.strip() and not handle.strip().startswith("//"):   # not "https://..."
            out.append({"platform": platform.strip() or None, "handle": handle.strip()})
        else:
            out.append({"platform": None, "handle": part})
    return out[:MAX_HANDLES]


def handles_text(handles: List[dict]) -> str:
    return "; ".join(f"{h['platform']}: {h['handle']}" if h.get("platform") else h["handle"] for h in handles)

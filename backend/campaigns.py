"""
Promo posts, organized.

- A campaign is one push with a goal and dates: "Chicago tour, Dec 3-7", "Red lace launch", "Weekend
  availability". Posts belong to it, and it can point at a tour or a set in the content library.
- A place is somewhere you post on a platform: a subreddit, a Telegram channel, a group. Each has its own rules
  (title format, verification, how often you may post), kept next to it so they don't have to be remembered.
  A wait in days turns into a warning when a post is planned too soon after the last one there.
- A snippet is a saved bit of text: links, hashtags, a sign-off.

As with the rest of the planner, sworkr posts nothing itself. This only keeps track.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()
_get_db: Optional[Callable] = None


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _owner(request: Request) -> int:
    return request.state.user["id"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(text: Optional[str], limit: int = 5000) -> Optional[str]:
    return (text or "").strip()[:limit] or None


# ==================== CAMPAIGNS ====================

class CampaignIn(BaseModel):
    name: str
    goal: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    tour_id: Optional[int] = None
    set_path: Optional[str] = None
    notes: Optional[str] = None
    archived: bool = False


def check_campaign(db, owner_id: int, campaign_id: Optional[int]):
    """A post can only join one of your own campaigns."""
    if campaign_id is not None and not db.execute(
            "SELECT 1 FROM campaigns WHERE id = ? AND owner_id = ?", (campaign_id, owner_id)).fetchone():
        raise HTTPException(status_code=400, detail="That campaign doesn't exist")


def _campaign_rows(db, owner_id: int, campaign_id: Optional[int] = None) -> List[dict]:
    out = []
    for r in db.execute("""
        SELECT c.*, t.name AS tour_name,
               (SELECT COUNT(*) FROM posts p WHERE p.campaign_id = c.id AND p.status != 'skipped') AS posts,
               (SELECT COUNT(*) FROM posts p WHERE p.campaign_id = c.id AND p.status = 'posted') AS posted,
               (SELECT COUNT(*) FROM posts p WHERE p.campaign_id = c.id AND p.status IN ('idea', 'ready', 'scheduled')
                                                   AND p.scheduled_at IS NOT NULL AND p.scheduled_at < ?) AS overdue,
               (SELECT MIN(p.scheduled_at) FROM posts p WHERE p.campaign_id = c.id AND p.status IN ('idea', 'ready', 'scheduled')
                                                          AND p.scheduled_at >= ?) AS next_due,
               (SELECT SUM(p.inquiries) FROM posts p WHERE p.campaign_id = c.id) AS inquiries,
               (SELECT GROUP_CONCAT(x.platform, '|') FROM (SELECT DISTINCT p.platform FROM posts p
                                                           WHERE p.campaign_id = c.id AND p.status != 'skipped') x) AS platforms
        FROM campaigns c LEFT JOIN tours t ON t.id = c.tour_id
        WHERE c.owner_id = ? AND (? IS NULL OR c.id = ?)
        ORDER BY c.archived, COALESCE(c.start_date, c.created_at) DESC, c.id DESC
    """, (_now(), _now(), owner_id, campaign_id, campaign_id)):
        d = dict(r)
        d["archived"] = bool(d["archived"])
        d["platforms"] = sorted(d["platforms"].split("|")) if d["platforms"] else []
        out.append(d)
    return out


def _campaign_values(db, owner_id: int, body: CampaignIn) -> tuple:
    import content
    name = _clean(body.name, 120)
    if not name:
        raise HTTPException(status_code=400, detail="Give the campaign a name")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="The campaign ends before it starts")
    if body.tour_id is not None and not db.execute(
            "SELECT 1 FROM tours WHERE id = ? AND owner_id = ?", (body.tour_id, owner_id)).fetchone():
        raise HTTPException(status_code=400, detail="That tour doesn't exist")
    return (name, _clean(body.goal, 300), body.start_date.isoformat() if body.start_date else None,
            body.end_date.isoformat() if body.end_date else None, body.tour_id, content.clean_path(body.set_path) or None,
            _clean(body.notes), int(body.archived))


@router.get("/api/campaigns")
def list_campaigns(request: Request):
    """Every campaign with how far along it is: posts planned, posted, overdue, the next one due, inquiries."""
    db = _get_db()
    try:
        return _campaign_rows(db, _owner(request))
    finally:
        db.close()


@router.post("/api/campaigns", status_code=201)
def create_campaign(body: CampaignIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        cur = db.execute("""
            INSERT INTO campaigns (name, goal, start_date, end_date, tour_id, set_path, notes, archived, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*_campaign_values(db, owner, body), owner, _now(), _now()))
        db.commit()
        return _campaign_rows(db, owner, cur.lastrowid)[0]
    finally:
        db.close()


@router.put("/api/campaigns/{campaign_id}")
def update_campaign(campaign_id: int, body: CampaignIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        if not _campaign_rows(db, owner, campaign_id):
            raise HTTPException(status_code=404, detail="Campaign not found")
        db.execute("""
            UPDATE campaigns SET name = ?, goal = ?, start_date = ?, end_date = ?, tour_id = ?, set_path = ?, notes = ?,
                   archived = ?, updated_at = ? WHERE id = ? AND owner_id = ?
        """, (*_campaign_values(db, owner, body), _now(), campaign_id, owner))
        db.commit()
        return _campaign_rows(db, owner, campaign_id)[0]
    finally:
        db.close()


@router.delete("/api/campaigns/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: int, request: Request):
    """The campaign goes; its posts stay in the planner, no longer grouped."""
    owner = _owner(request)
    db = _get_db()
    try:
        db.execute("UPDATE posts SET campaign_id = NULL WHERE campaign_id = ? AND owner_id = ?", (campaign_id, owner))
        db.execute("DELETE FROM campaigns WHERE id = ? AND owner_id = ?", (campaign_id, owner))
        db.commit()
    finally:
        db.close()


# ==================== PLACES YOU POST IN ====================

class PlaceIn(BaseModel):
    platform: str
    name: str
    rules: Optional[str] = None
    wait_days: Optional[int] = None      # the place's own limit: at most one post every this many days
    link: Optional[str] = None
    archived: bool = False


def _place_rows(db, owner_id: int, place_id: Optional[int] = None) -> List[dict]:
    out = []
    for r in db.execute("""
        SELECT pl.*,
               (SELECT MAX(COALESCE(p.posted_at, p.scheduled_at)) FROM posts p
                WHERE p.owner_id = pl.owner_id AND p.status = 'posted' AND LOWER(p.platform) = LOWER(pl.platform)
                  AND LOWER(p.place) = LOWER(pl.name)) AS last_posted,
               (SELECT COUNT(*) FROM posts p
                WHERE p.owner_id = pl.owner_id AND p.status = 'posted' AND LOWER(p.platform) = LOWER(pl.platform)
                  AND LOWER(p.place) = LOWER(pl.name)) AS posted
        FROM post_places pl WHERE pl.owner_id = ? AND (? IS NULL OR pl.id = ?)
        ORDER BY pl.archived, pl.platform COLLATE NOCASE, pl.name COLLATE NOCASE
    """, (owner_id, place_id, place_id)):
        d = dict(r)
        d["archived"] = bool(d["archived"])
        d["free_from"] = None
        if d["last_posted"] and d["wait_days"]:
            d["free_from"] = (datetime.fromisoformat(d["last_posted"]) + timedelta(days=d["wait_days"])).isoformat(timespec="seconds")
        out.append(d)
    return out


def _place_values(db, owner_id: int, body: PlaceIn, place_id: Optional[int] = None) -> tuple:
    platform, name = _clean(body.platform, 60), _clean(body.name, 120)
    if not platform or not name:
        raise HTTPException(status_code=400, detail="Say which platform, and the place's name")
    if body.wait_days is not None and not (0 <= body.wait_days <= 3650):
        raise HTTPException(status_code=400, detail="The wait is 0 to 3650 days")
    link = _clean(body.link, 500)
    if link and not link.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="The link must start with https://")
    if db.execute("SELECT 1 FROM post_places WHERE owner_id = ? AND LOWER(platform) = LOWER(?) AND LOWER(name) = LOWER(?) AND id IS NOT ?",
                  (owner_id, platform, name, place_id)).fetchone():
        raise HTTPException(status_code=409, detail="You already have that place")
    return platform, name, _clean(body.rules), body.wait_days, link, int(body.archived)


@router.get("/api/post-places")
def list_places(request: Request):
    db = _get_db()
    try:
        return _place_rows(db, _owner(request))
    finally:
        db.close()


@router.post("/api/post-places", status_code=201)
def create_place(body: PlaceIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        cur = db.execute("""
            INSERT INTO post_places (platform, name, rules, wait_days, link, archived, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*_place_values(db, owner, body), owner, _now(), _now()))
        db.commit()
        return _place_rows(db, owner, cur.lastrowid)[0]
    finally:
        db.close()


@router.put("/api/post-places/{place_id}")
def update_place(place_id: int, body: PlaceIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        if not _place_rows(db, owner, place_id):
            raise HTTPException(status_code=404, detail="Place not found")
        db.execute("""
            UPDATE post_places SET platform = ?, name = ?, rules = ?, wait_days = ?, link = ?, archived = ?, updated_at = ?
            WHERE id = ? AND owner_id = ?
        """, (*_place_values(db, owner, body, place_id), _now(), place_id, owner))
        db.commit()
        return _place_rows(db, owner, place_id)[0]
    finally:
        db.close()


@router.delete("/api/post-places/{place_id}", status_code=204)
def delete_place(place_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM post_places WHERE id = ? AND owner_id = ?", (place_id, _owner(request)))
        db.commit()
    finally:
        db.close()


def place_warnings(db, owner_id: int, platform: str, place: Optional[str], planned: Optional[datetime],
                   exclude_id: Optional[int] = None) -> List[str]:
    """This place allows a post every N days, and the last one there was more recent than that."""
    if not place:
        return []
    saved = db.execute("SELECT name, wait_days FROM post_places WHERE owner_id = ? AND LOWER(platform) = LOWER(?) AND LOWER(name) = LOWER(?)",
                       (owner_id, platform, place)).fetchone()
    if not saved or not saved["wait_days"]:
        return []
    planned = planned or datetime.now(timezone.utc)
    planned = planned if planned.tzinfo else planned.replace(tzinfo=timezone.utc)
    window = timedelta(days=saved["wait_days"])
    for p in db.execute("""
        SELECT COALESCE(posted_at, scheduled_at) AS at, status FROM posts
        WHERE owner_id = ? AND id IS NOT ? AND status IN ('posted', 'scheduled', 'ready') AND LOWER(platform) = LOWER(?)
          AND LOWER(place) = LOWER(?) AND COALESCE(posted_at, scheduled_at) IS NOT NULL
    """, (owner_id, exclude_id, platform, place)):
        other = datetime.fromisoformat(p["at"])
        if abs(planned - other) < window:
            verb = "posted" if p["status"] == "posted" else "have another post planned"
            return [f"{saved['name']} allows one post every {saved['wait_days']} days, and you {verb} there on {other.date().isoformat()}"]
    return []


# ==================== SAVED TEXT ====================

class SnippetIn(BaseModel):
    label: str
    body: str


def _snippet_values(body: SnippetIn) -> tuple:
    label, text = _clean(body.label, 60), _clean(body.body, 5000)
    if not label or not text:
        raise HTTPException(status_code=400, detail="A snippet needs a name and some text")
    return label, text


@router.get("/api/snippets")
def list_snippets(request: Request):
    db = _get_db()
    try:
        return [dict(r) for r in db.execute("SELECT id, label, body FROM snippets WHERE owner_id = ? ORDER BY label COLLATE NOCASE",
                                            (_owner(request),))]
    finally:
        db.close()


@router.post("/api/snippets", status_code=201)
def create_snippet(body: SnippetIn, request: Request):
    db = _get_db()
    try:
        label, text = _snippet_values(body)
        cur = db.execute("INSERT INTO snippets (label, body, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                         (label, text, _owner(request), _now(), _now()))
        db.commit()
        return {"id": cur.lastrowid, "label": label, "body": text}
    finally:
        db.close()


@router.put("/api/snippets/{snippet_id}")
def update_snippet(snippet_id: int, body: SnippetIn, request: Request):
    db = _get_db()
    try:
        label, text = _snippet_values(body)
        done = db.execute("UPDATE snippets SET label = ?, body = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                          (label, text, _now(), snippet_id, _owner(request)))
        if not done.rowcount:
            raise HTTPException(status_code=404, detail="Snippet not found")
        db.commit()
        return {"id": snippet_id, "label": label, "body": text}
    finally:
        db.close()


@router.delete("/api/snippets/{snippet_id}", status_code=204)
def delete_snippet(snippet_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM snippets WHERE id = ? AND owner_id = ?", (snippet_id, _owner(request)))
        db.commit()
    finally:
        db.close()

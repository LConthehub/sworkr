"""
Posting to social networks, and the numbers that come back.

Three networks, each connected with the person's own credentials (no sworkr company account in the middle):
- Bluesky: handle + an app password (Settings > Privacy and security > App passwords). Any PDS works.
- Mastodon: the server + an access token (Preferences > Development > New application, scopes
  read:statuses write:statuses write:media).
- Reddit: the person's own "script" app (reddit.com/prefs/apps): client id + secret, username + password.
  Text posts to a subreddit (the post's "place"); pictures are posted on Reddit by hand for now.

A planned post (content.py) can be posted now, or set to post itself at its scheduled time. Pictures come
from the content library (images only, up to 4). Each account has a default content label (none,
suggestive, nudity, porn), sent as each network expects (Bluesky self-labels, Mastodon "sensitive",
Reddit NSFW), so posts follow the networks' rules about adult content.

Numbers: likes, reposts, replies (and views when a CSV export has them) per post. Fetched from the
networks for posts made through sworkr, or imported from a CSV export for anything else (matched by link).

Credentials are sealed with vault (AES-GCM) and never sent back to the browser.
"""

import csv
import io
import json
import logging
import mimetypes
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import content
import csv_io
import vault

log = logging.getLogger("sworkr.social")
router = APIRouter()
_get_db: Optional[Callable] = None
TRANSPORT: Optional[httpx.BaseTransport] = None     # tests put a fake network here
TIMEOUT = 30
NETWORKS = ("bluesky", "mastodon", "reddit")
LABELS = ("none", "suggestive", "nudity", "porn")
MAX_IMAGES = 4
BLUESKY_MAX_IMAGE = 976_000          # Bluesky refuses image blobs over about 976 KB
SECRET_NAME = "social_secret"
STATS_DAYS = 60                      # refresh numbers for posts this recent


class SocialError(Exception):
    pass


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _client(**kw) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=TRANSPORT, follow_redirects=False, **kw)


def _check(r: httpx.Response, what: str) -> dict:
    if r.status_code in (401, 403):
        raise SocialError(f"{what}: the network refused the login (check the password or token)")
    if r.status_code >= 400:
        try:
            body = r.json()
            detail = body.get("message") or body.get("error") or body.get("error_description") or ""
        except ValueError:
            detail = ""
        raise SocialError(f"{what}: the network said {r.status_code} {str(detail)[:200]}".strip())
    try:
        return r.json()
    except ValueError:
        raise SocialError(f"{what}: the network sent something unexpected")


def clean_server(raw: Optional[str], default: Optional[str] = None) -> str:
    raw = (raw or "").strip() or (default or "")
    if not raw:
        raise HTTPException(status_code=400, detail="Which server is the account on?")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme != "https" or not parts.hostname:
        raise HTTPException(status_code=400, detail="The server must be an https:// address")
    return f"https://{parts.netloc}"


# ==================== THE NETWORKS ====================

URL_RE = re.compile(r"https?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]]")
TAG_RE = re.compile(r"(?<![\w#])#([^\s#.,;:!?()\[\]]{1,64})")


def bluesky_facets(text: str) -> List[dict]:
    """Links and hashtags, marked by their byte positions (that's how Bluesky makes them clickable)."""
    facets = []
    for m in URL_RE.finditer(text):
        start, end = len(text[:m.start()].encode()), len(text[:m.end()].encode())
        facets.append({"index": {"byteStart": start, "byteEnd": end},
                       "features": [{"$type": "app.bsky.richtext.facet#link", "uri": m.group(0)}]})
    for m in TAG_RE.finditer(text):
        if m.group(1).isdigit():
            continue
        start, end = len(text[:m.start()].encode()), len(text[:m.end()].encode())
        facets.append({"index": {"byteStart": start, "byteEnd": end},
                       "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": m.group(1)}]})
    return facets


class Bluesky:
    LIMIT = 300

    def __init__(self, server: str, handle: str, password: str):
        self.server, self.handle, self.password = server, handle.lstrip("@"), password
        self.http = _client()
        self.jwt = self.did = None

    def close(self):
        self.http.close()

    def login(self) -> str:
        data = _check(self.http.post(f"{self.server}/xrpc/com.atproto.server.createSession",
                                     json={"identifier": self.handle, "password": self.password}), "Bluesky sign-in")
        self.jwt, self.did, self.handle = data["accessJwt"], data["did"], data.get("handle") or self.handle
        return self.handle

    def _auth(self) -> dict:
        if not self.jwt:
            self.login()
        return {"Authorization": f"Bearer {self.jwt}"}

    def post(self, text: str, images: List[tuple], label: str) -> dict:
        if len(text) > self.LIMIT:
            raise SocialError(f"Bluesky posts can be up to {self.LIMIT} characters; this one is {len(text)}")
        record = {"$type": "app.bsky.feed.post", "text": text, "createdAt": _now().replace("+00:00", "Z")}
        facets = bluesky_facets(text)
        if facets:
            record["facets"] = facets
        if images:
            embedded = []
            for name, data, mime, alt in images:
                if len(data) > BLUESKY_MAX_IMAGE:
                    raise SocialError(f"{name} is too big for Bluesky (the limit is about 1 MB); post a smaller copy")
                blob = _check(self.http.post(f"{self.server}/xrpc/com.atproto.repo.uploadBlob", content=data,
                                             headers={**self._auth(), "Content-Type": mime}), "Bluesky picture upload")
                embedded.append({"alt": alt[:2000], "image": blob["blob"]})
            record["embed"] = {"$type": "app.bsky.embed.images", "images": embedded}
        if label in ("suggestive", "nudity", "porn"):
            record["labels"] = {"$type": "com.atproto.label.defs#selfLabels",
                                "values": [{"val": "sexual" if label == "suggestive" else label}]}
        data = _check(self.http.post(f"{self.server}/xrpc/com.atproto.repo.createRecord", headers=self._auth(),
                                     json={"repo": self.did, "collection": "app.bsky.feed.post", "record": record}),
                      "Bluesky post")
        rkey = data["uri"].rsplit("/", 1)[-1]
        return {"remote_id": data["uri"], "url": f"https://bsky.app/profile/{self.handle}/post/{rkey}"}

    def stats(self, ids: List[str]) -> dict:
        out = {}
        for i in range(0, len(ids), 25):
            data = _check(self.http.get(f"{self.server}/xrpc/app.bsky.feed.getPosts", headers=self._auth(),
                                        params=[("uris", u) for u in ids[i:i + 25]]), "Bluesky numbers")
            for p in data.get("posts", []):
                out[p["uri"]] = {"likes": p.get("likeCount", 0), "reposts": p.get("repostCount", 0) + p.get("quoteCount", 0),
                                 "replies": p.get("replyCount", 0)}
        return out


class Mastodon:
    LIMIT = 500

    def __init__(self, server: str, token: str):
        self.server = server
        self.http = _client(headers={"Authorization": f"Bearer {token}"})

    def close(self):
        self.http.close()

    def login(self) -> str:
        data = _check(self.http.get(f"{self.server}/api/v1/accounts/verify_credentials"), "Mastodon sign-in")
        return "@" + data["acct"] + "@" + urlsplit(self.server).hostname

    def post(self, text: str, images: List[tuple], label: str, key: str = "") -> dict:
        if len(text) > self.LIMIT:
            raise SocialError(f"Mastodon posts are usually up to {self.LIMIT} characters; this one is {len(text)}")
        media = []
        for name, data, mime, alt in images:
            m = _check(self.http.post(f"{self.server}/api/v2/media", files={"file": (name, data, mime)},
                                      data={"description": alt[:1500]} if alt else None),
                       "Mastodon picture upload")
            media.append(m["id"])
        form = {"status": text, "media_ids[]": media, "sensitive": "true" if label != "none" else "false"}
        headers = {"Idempotency-Key": key} if key else {}    # a retry never posts twice
        data = _check(self.http.post(f"{self.server}/api/v1/statuses", data=form, headers=headers), "Mastodon post")
        return {"remote_id": data["id"], "url": data.get("url") or data.get("uri")}

    def stats(self, ids: List[str]) -> dict:
        out = {}
        for i in ids:
            r = self.http.get(f"{self.server}/api/v1/statuses/{i}")
            if r.status_code == 404:
                continue      # deleted
            d = _check(r, "Mastodon numbers")
            out[i] = {"likes": d.get("favourites_count", 0), "reposts": d.get("reblogs_count", 0),
                      "replies": d.get("replies_count", 0)}
        return out


class Reddit:
    LIMIT = 40000

    def __init__(self, client_id: str, client_secret: str, username: str, password: str):
        self.client_id, self.client_secret, self.username, self.password = client_id, client_secret, username, password
        self.http = _client(headers={"User-Agent": "sworkr:selfhosted:1.0 (personal script)"})
        self.token = None

    def close(self):
        self.http.close()

    def login(self) -> str:
        data = _check(self.http.post("https://www.reddit.com/api/v1/access_token",
                                     auth=(self.client_id, self.client_secret),
                                     data={"grant_type": "password", "username": self.username, "password": self.password}),
                      "Reddit sign-in")
        if not data.get("access_token"):
            raise SocialError("Reddit sign-in: " + str(data.get("error") or "refused (check the app id, secret and password)"))
        self.token = data["access_token"]
        return "u/" + self.username

    def _auth(self) -> dict:
        if not self.token:
            self.login()
        return {"Authorization": f"bearer {self.token}"}

    def _upload(self, name: str, data: bytes, mime: str) -> str:
        """Reddit takes pictures in two steps: ask for an upload slot, then send the file to it."""
        lease = _check(self.http.post("https://oauth.reddit.com/api/media/asset.json", headers=self._auth(),
                                      data={"filepath": name, "mimetype": mime}), "Reddit picture upload")
        args = lease.get("args") or {}
        action = args.get("action") or ""
        if action.startswith("//"):
            action = "https:" + action
        if not action.startswith("https://"):
            raise SocialError("Reddit picture upload: Reddit sent an upload address sworkr doesn't understand")
        fields = {f["name"]: f["value"] for f in args.get("fields", [])}
        r = self.http.post(action, data=fields, files={"file": (name, data, mime)})
        if r.status_code >= 300:
            raise SocialError(f"Reddit picture upload: the upload was refused ({r.status_code})")
        return lease["asset"]["asset_id"]

    def post(self, text: str, images: List[tuple], label: str, subreddit: Optional[str]) -> dict:
        sr = (subreddit or "").strip().removeprefix("r/").removeprefix("/r/").strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_]{2,21}", sr):
            raise SocialError("Put the subreddit in the post's \"where\" field (like r/example)")
        title, _, body = text.strip().partition("\n")
        if not title.strip():
            raise SocialError("The first line of the caption is the Reddit title, and it's empty")
        nsfw = label in ("nudity", "porn")
        if images:
            items = [{"media_id": self._upload(name, data, mime), "caption": alt[:180], "outbound_url": ""}
                     for name, data, mime, alt in images]
            data = _check(self.http.post("https://oauth.reddit.com/api/submit_gallery_post.json", headers=self._auth(), json={
                "sr": sr, "title": title.strip()[:300], "items": items, "nsfw": nsfw, "spoiler": False,
                "sendreplies": True, "api_type": "json", "show_error_list": True, "validate_on_submit": True,
                "text": body.strip()}), "Reddit post")
            errors = data.get("json", {}).get("errors") or []
            if errors:
                raise SocialError("Reddit said: " + "; ".join(str(e) for e in errors)[:300])
            d = data["json"]["data"]
            rid = d.get("id") or ""
            return {"remote_id": rid if rid.startswith("t3_") else (f"t3_{rid}" if rid else None), "url": d.get("url")}
        data = _check(self.http.post("https://oauth.reddit.com/api/submit", headers=self._auth(), data={
            "sr": sr, "kind": "self", "title": title.strip()[:300], "text": body.strip(),
            "nsfw": "true" if nsfw else "false", "api_type": "json"}), "Reddit post")
        errors = data.get("json", {}).get("errors") or []
        if errors:
            raise SocialError("Reddit said: " + "; ".join(" ".join(str(x) for x in e[1:2]) for e in errors))
        d = data["json"]["data"]
        return {"remote_id": d.get("name"), "url": d.get("url")}

    def stats(self, ids: List[str]) -> dict:
        out = {}
        for i in range(0, len(ids), 100):
            data = _check(self.http.get("https://oauth.reddit.com/api/info", headers=self._auth(),
                                        params={"id": ",".join(ids[i:i + 100])}), "Reddit numbers")
            for c in data.get("data", {}).get("children", []):
                d = c.get("data", {})
                out[d.get("name")] = {"likes": d.get("score", 0), "reposts": d.get("num_crossposts", 0),
                                      "replies": d.get("num_comments", 0)}
        return out


def connect(account: dict, secret: dict):
    """The right network client for a saved account."""
    if account["network"] == "bluesky":
        return Bluesky(account["server"], account["handle"], secret.get("password", ""))
    if account["network"] == "mastodon":
        return Mastodon(account["server"], secret.get("token", ""))
    return Reddit(account["client_id"] or "", secret.get("client_secret", ""), account["handle"], secret.get("password", ""))


# ==================== ACCOUNTS ====================

def _account_row(r) -> dict:
    d = dict(r)
    d.pop("secret", None)
    d.pop("owner_id", None)
    return d


def accounts(db, owner: int) -> List[dict]:
    return [_account_row(r) for r in db.execute("SELECT * FROM social_accounts WHERE owner_id = ? ORDER BY network, handle", (owner,))]


def _account(db, owner: int, account_id: int):
    r = db.execute("SELECT * FROM social_accounts WHERE id = ? AND owner_id = ?", (account_id, owner)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Account not found")
    return dict(r)


def _secret(account: dict) -> dict:
    raw = vault.unseal(SECRET_NAME, account["secret"])
    if raw is None:
        raise SocialError("The saved password for this account can't be read on this computer; connect it again")
    return json.loads(raw or "{}")


class AccountIn(BaseModel):
    network: str
    server: Optional[str] = None          # Bluesky (default bsky.social) and Mastodon
    handle: Optional[str] = None          # Bluesky handle, Reddit username
    password: Optional[str] = None        # Bluesky app password, Reddit password
    token: Optional[str] = None           # Mastodon access token
    client_id: Optional[str] = None       # Reddit app
    client_secret: Optional[str] = None   # Reddit app
    label: str = "none"


@router.get("/api/social/accounts")
def list_accounts(request: Request):
    db = _get_db()
    try:
        return accounts(db, request.state.user["id"])
    finally:
        db.close()


@router.post("/api/social/accounts", status_code=201)
def add_account(body: AccountIn, request: Request):
    """Sign in once to check the details, then save them (sealed)."""
    if content._demo():
        raise HTTPException(status_code=403, detail="Some features are only available in the full version. "
                                                    "Never enter real account details in a demo.")
    if body.network not in NETWORKS:
        raise HTTPException(status_code=400, detail="Bluesky, Mastodon or Reddit")
    if body.label not in LABELS:
        raise HTTPException(status_code=400, detail="Unknown content label")
    handle = (body.handle or "").strip().lstrip("@")
    if body.network == "bluesky":
        server, secret, client_id = clean_server(body.server, "https://bsky.social"), {"password": (body.password or "").strip()}, None
        if not handle or not secret["password"]:
            raise HTTPException(status_code=400, detail="Your handle and an app password")
    elif body.network == "mastodon":
        server, secret, client_id = clean_server(body.server), {"token": (body.token or "").strip()}, None
        if not secret["token"]:
            raise HTTPException(status_code=400, detail="An access token from your server's Development settings")
    else:
        server, client_id = "https://oauth.reddit.com", (body.client_id or "").strip()
        secret = {"client_secret": (body.client_secret or "").strip(), "password": body.password or ""}
        handle = handle.removeprefix("u/")
        if not (client_id and secret["client_secret"] and handle and secret["password"]):
            raise HTTPException(status_code=400, detail="Your app's id and secret, your username and password")
    account = {"network": body.network, "server": server, "handle": handle, "client_id": client_id}
    net = connect(account, secret)
    try:
        name = net.login()
    except (SocialError, httpx.HTTPError) as e:
        raise HTTPException(status_code=400, detail=str(e) or "Couldn't reach the network")
    finally:
        net.close()
    owner = request.state.user["id"]
    db = _get_db()
    try:
        cur = db.execute("INSERT INTO social_accounts (owner_id, network, server, handle, display, client_id, secret, label, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (owner, body.network, server, handle, name, client_id, vault.seal(SECRET_NAME, json.dumps(secret)),
                          body.label, _now()))
        db.commit()
        return _account_row(db.execute("SELECT * FROM social_accounts WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        db.close()


class AccountEdit(BaseModel):
    label: str


@router.put("/api/social/accounts/{account_id}")
def edit_account(account_id: int, body: AccountEdit, request: Request):
    if body.label not in LABELS:
        raise HTTPException(status_code=400, detail="Unknown content label")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _account(db, owner, account_id)
        db.execute("UPDATE social_accounts SET label = ? WHERE id = ? AND owner_id = ?", (body.label, account_id, owner))
        db.commit()
        return _account_row(db.execute("SELECT * FROM social_accounts WHERE id = ?", (account_id,)).fetchone())
    finally:
        db.close()


@router.delete("/api/social/accounts/{account_id}", status_code=204)
def remove_account(account_id: int, request: Request):
    """Forget the account here. Posts already made stay on the network (and in the planner)."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        db.execute("UPDATE posts SET auto_post = 0 WHERE social_account_id = ? AND owner_id = ? AND status != 'posted'",
                   (account_id, owner))
        db.execute("DELETE FROM social_accounts WHERE id = ? AND owner_id = ?", (account_id, owner))
        db.commit()
    finally:
        db.close()


# ==================== POSTING ====================

def _images(library, post: dict) -> List[tuple]:
    paths = [p for p in post["file_paths"] if (mimetypes.guess_type(p)[0] or "") in ("image/jpeg", "image/png", "image/webp", "image/gif")]
    others = [p for p in post["file_paths"] if p not in paths]
    if others:
        raise SocialError("Only pictures (jpg, png, webp, gif) can be posted from here; "
                          f"post {others[0].rsplit('/', 1)[-1]} on the network yourself")
    if len(paths) > MAX_IMAGES:
        raise SocialError(f"Up to {MAX_IMAGES} pictures per post")
    if paths and library is None:
        raise SocialError("Connect your content library so the pictures can be read")
    out = []
    for p in paths:
        try:
            out.append((p.rsplit("/", 1)[-1], library.read(p), mimetypes.guess_type(p)[0], (post.get("alt_text") or {}).get(p, "")))
        except content.LibraryError as e:
            raise SocialError(f"Couldn't read {p} from the library: {e}")
    return out


def publish(db, owner: int, post_id: int, account_id: int, library, label: Optional[str] = None) -> dict:
    """Post it now. On success the post is marked posted with its link; on failure nothing changes but the error."""
    post = content.get_post(db, post_id, owner)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post["status"] == "posted":
        raise SocialError("This one is already marked as posted")
    account = _account(db, owner, account_id)
    label = label if label in LABELS else account["label"]
    text = (post["caption"] or "").strip()
    images = _images(library, post)
    if not text and not images:
        raise SocialError("There's nothing to post: add a caption or pictures")
    net = connect(account, _secret(account))
    try:
        if account["network"] == "bluesky":
            result = net.post(text, images, label)
        elif account["network"] == "mastodon":
            result = net.post(text, images, label, key=f"sworkr-{owner}-{post_id}")
        else:
            result = net.post(text, images, label, post.get("place"))
    except httpx.HTTPError:
        raise SocialError(f"Couldn't reach {account['network'].title()}")
    finally:
        net.close()
    db.execute("UPDATE posts SET status = 'posted', posted_at = ?, post_url = ?, remote_id = ?, social_account_id = ?, "
               "auto_post = 0, post_error = NULL, updated_at = ? WHERE id = ? AND owner_id = ?",
               (_now(), result["url"], result["remote_id"], account_id, _now(), post_id, owner))
    db.commit()
    content._queue_sync([post_id], owner)
    return content.get_post(db, post_id, owner)


class PublishIn(BaseModel):
    account_id: int
    label: Optional[str] = None
    when: str = "now"                # "now", or "scheduled": post itself at the post's scheduled time


def _library_or_none(db, owner: int):
    s = content.load_settings(db, owner)
    if not s["kind"] and not content._demo():
        return None
    try:
        return content.open_library(s)
    except content.LibraryError:
        return None


@router.post("/api/posts/{post_id}/publish")
def publish_post(post_id: int, body: PublishIn, request: Request):
    if content._demo():
        raise HTTPException(status_code=403, detail="Some features are only available in the full version.")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        post = content.get_post(db, post_id, owner)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        _account(db, owner, body.account_id)
        if body.when == "scheduled":
            if not post["scheduled_at"]:
                raise HTTPException(status_code=400, detail="Give the post a time first")
            db.execute("UPDATE posts SET auto_post = 1, social_account_id = ?, status = CASE WHEN status = 'posted' THEN status "
                       "ELSE 'scheduled' END, post_error = NULL, updated_at = ? WHERE id = ? AND owner_id = ?",
                       (body.account_id, _now(), post_id, owner))
            db.commit()
            return content.get_post(db, post_id, owner)
        try:
            return publish(db, owner, post_id, body.account_id, _library_or_none(db, owner), body.label)
        except SocialError as e:
            db.execute("UPDATE posts SET post_error = ? WHERE id = ? AND owner_id = ?", (str(e)[:500], post_id, owner))
            db.commit()
            raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.delete("/api/posts/{post_id}/publish")
def stop_auto_post(post_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        db.execute("UPDATE posts SET auto_post = 0 WHERE id = ? AND owner_id = ?", (post_id, owner))
        db.commit()
        return content.get_post(db, post_id, owner)
    finally:
        db.close()


def run_due(get_db: Callable, now: Optional[datetime] = None) -> int:
    """Post everything whose time has come. A failure turns auto-posting off for that post and keeps the reason."""
    now = now or datetime.now(timezone.utc)
    db = get_db()
    done = 0
    try:
        due = db.execute("SELECT id, owner_id, social_account_id FROM posts WHERE auto_post = 1 AND status != 'posted' "
                         "AND social_account_id IS NOT NULL AND scheduled_at <= ? ORDER BY scheduled_at LIMIT 20",
                         (now.isoformat(timespec="seconds"),)).fetchall()
        for p in due:
            try:
                publish(db, p["owner_id"], p["id"], p["social_account_id"], _library_or_none(db, p["owner_id"]))
                done += 1
            except (SocialError, HTTPException) as e:
                reason = e.detail if isinstance(e, HTTPException) else str(e)
                db.execute("UPDATE posts SET auto_post = 0, post_error = ? WHERE id = ?", (str(reason)[:500], p["id"]))
                db.commit()
                tell_failed(db, p["owner_id"], str(reason))
            except Exception:
                log.exception("Auto-post %s failed", p["id"])
                db.execute("UPDATE posts SET auto_post = 0, post_error = 'Something went wrong posting it' WHERE id = ?", (p["id"],))
                db.commit()
                tell_failed(db, p["owner_id"], "Something went wrong posting it")
    finally:
        db.close()
    return done


def tell_failed(db, owner: int, reason: str):
    """A push through the person's ntfy, if they set it up. Discreet unless they chose to show details."""
    import ntfy
    try:
        s = ntfy.load_settings(db, owner)
        if not s["enabled"] or not s["topic"]:
            return
        if s["details"]:
            ntfy.publish(s, "A scheduled post didn't go out", f"{reason[:300]} It's back in your plan to post by hand.", tags=["warning"])
        else:
            ntfy.publish(s, "Something needs a look", "Open sworkr when you can.", tags=["warning"])
    except Exception:
        log.warning("Couldn't send the ntfy push for a failed post", exc_info=True)


def _worker():
    while True:
        time.sleep(60)
        try:
            run_due(_get_db)
        except Exception:
            log.exception("Auto-posting stopped for a moment")


def start(get_db: Callable, background: bool = True):
    global _get_db
    _get_db = get_db
    if background:
        threading.Thread(target=_worker, name="social", daemon=True).start()


# ==================== NUMBERS ====================

def _save_stats(db, post_id: int, s: dict, source: str):
    db.execute("INSERT INTO post_stats (post_id, likes, reposts, replies, views, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
               "ON CONFLICT(post_id) DO UPDATE SET likes = COALESCE(excluded.likes, post_stats.likes), "
               "reposts = COALESCE(excluded.reposts, post_stats.reposts), replies = COALESCE(excluded.replies, post_stats.replies), "
               "views = COALESCE(excluded.views, post_stats.views), "
               "source = excluded.source, fetched_at = excluded.fetched_at",
               (post_id, s.get("likes"), s.get("reposts"), s.get("replies"), s.get("views"), source, _now()))


@router.post("/api/social/stats/refresh")
def refresh_stats(request: Request):
    """Fetch the latest numbers for recent posts made through sworkr."""
    owner = request.state.user["id"]
    since = (datetime.now(timezone.utc) - timedelta(days=STATS_DAYS)).isoformat(timespec="seconds")
    db = _get_db()
    updated, problems = 0, []
    try:
        for account in [dict(a) for a in db.execute("SELECT * FROM social_accounts WHERE owner_id = ?", (owner,))]:
            rows = db.execute("SELECT id, remote_id FROM posts WHERE owner_id = ? AND social_account_id = ? AND remote_id IS NOT NULL "
                              "AND posted_at >= ?", (owner, account["id"], since)).fetchall()
            if not rows:
                continue
            try:
                net = connect(account, _secret(account))
                try:
                    found = net.stats([r["remote_id"] for r in rows])
                finally:
                    net.close()
            except (SocialError, httpx.HTTPError) as e:
                problems.append(f"{account['display'] or account['handle']}: {e}")
                continue
            for r in rows:
                if r["remote_id"] in found:
                    _save_stats(db, r["id"], found[r["remote_id"]], "network")
                    updated += 1
        db.commit()
        return {"updated": updated, "problems": problems}
    finally:
        db.close()


@router.get("/api/social/stats")
def stats(request: Request, days: int = Query(90, ge=7, le=3650)):
    """Posted posts with their numbers, and totals by platform."""
    owner = request.state.user["id"]
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    db = _get_db()
    try:
        rows = [dict(r) for r in db.execute(
            "SELECT p.id, p.platform, p.account, p.place, p.caption, p.posted_at, p.post_url, p.inquiries, "
            "s.likes, s.reposts, s.replies, s.views, s.fetched_at FROM posts p LEFT JOIN post_stats s ON s.post_id = p.id "
            "WHERE p.owner_id = ? AND p.status = 'posted' AND p.posted_at >= ? ORDER BY p.posted_at DESC", (owner, since))]
        by = {}
        for r in rows:
            r["caption"] = (r["caption"] or "")[:140]
            t = by.setdefault(r["platform"], {"platform": r["platform"], "posts": 0, "likes": 0, "reposts": 0,
                                              "replies": 0, "views": 0, "inquiries": 0})
            t["posts"] += 1
            for k in ("likes", "reposts", "replies", "views", "inquiries"):
                t[k] += r[k] or 0
        return {"days": days, "platforms": sorted(by.values(), key=lambda t: -t["posts"]), "posts": rows}
    finally:
        db.close()


COLUMNS = {
    "url": ("url", "link", "post url", "post link", "permalink", "post_url"),
    "likes": ("likes", "favourites", "favorites", "reactions", "score", "upvotes", "hearts"),
    "reposts": ("reposts", "shares", "boosts", "retweets", "reblogs"),
    "replies": ("replies", "comments"),
    "views": ("views", "impressions", "reach", "plays"),
}


def _number(raw: Optional[str]) -> Optional[int]:
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kKmM]?)", raw)
    if not m:
        return None
    n = float(m.group(1)) * {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2).lower()]
    return int(n)


def _norm_url(u: str) -> str:
    u = (u or "").strip().lower().split("?")[0].rstrip("/")
    return re.sub(r"^https?://(www\.|old\.|m\.)?", "", u)


@router.post("/api/social/stats/import")
async def import_stats(request: Request):
    """Numbers from a platform's CSV export (sent as the request body), matched to your posts by their links."""
    owner = request.state.user["id"]
    text = await csv_io._body(request)
    reader = csv.DictReader(io.StringIO(text))
    heads = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
    cols = {k: next((heads[n] for n in names if n in heads), None) for k, names in COLUMNS.items()}
    if not cols["url"]:
        raise HTTPException(status_code=400, detail="The file needs a column with each post's link (url or link)")
    db = _get_db()
    try:
        posts = {_norm_url(r["post_url"]): r["id"] for r in db.execute(
            "SELECT id, post_url FROM posts WHERE owner_id = ? AND post_url IS NOT NULL", (owner,))}
        matched = unmatched = 0
        for row in reader:
            pid = posts.get(_norm_url(row.get(cols["url"]) or ""))
            if not pid:
                unmatched += 1
                continue
            _save_stats(db, pid, {k: _number(row.get(c)) if c else None for k, c in cols.items() if k != "url"}, "csv")
            matched += 1
        db.commit()
        return {"matched": matched, "unmatched": unmatched}
    finally:
        db.close()

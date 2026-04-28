import csv
import os
import re
import logging
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import requests as http_requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = App(token=os.environ["SLACK_BOT_TOKEN"])

ALERT_CHANNEL_ID = os.environ["ALERT_CHANNEL_ID"]
RESPONSE_TIMEOUT_SECONDS = int(os.environ.get("RESPONSE_TIMEOUT_MINUTES", "120")) * 60

SB_URL = os.environ["SUPABASE_URL"]
SB_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_ANON_KEY"]

_DIR = os.path.dirname(__file__)

EASTERN = ZoneInfo("America/New_York")
BUSINESS_OPEN_HOUR  = 9
BUSINESS_CLOSE_HOUR = 17
BUSINESS_CLOSE_MIN  = 30

WEEKEND_AUTO_REPLY = (
    "Hi there! We received your message, but our team is away for the weekend. "
    "We'll be back Monday morning and will make sure to follow up with you then. "
    "Thanks for being patient!"
)


def _business_hours_status() -> tuple[bool, bool]:
    """Return (is_open, is_weekend) based on current Eastern time."""
    now = datetime.now(EASTERN)
    is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6
    if is_weekend:
        return False, True
    start = now.replace(hour=BUSINESS_OPEN_HOUR, minute=0, second=0, microsecond=0)
    end   = now.replace(hour=BUSINESS_CLOSE_HOUR, minute=BUSINESS_CLOSE_MIN, second=0, microsecond=0)
    return start <= now <= end, False


# ── Load config from CSVs ─────────────────────────────────────────────────────

def _load_responder_ids() -> set[str]:
    """Load Savvy staff user IDs from member_directory.csv (column: Member ID)."""
    path = os.path.join(_DIR, "member_directory.csv")
    ids = set()
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            uid = row.get("Member ID", "").strip()
            if uid:
                ids.add(uid)
    return ids


def _load_monitored_channels() -> dict[str, str]:
    """Load ops channel IDs from ops_channels.csv. Returns {channel_id: channel_name}."""
    path = os.path.join(_DIR, "ops_channels.csv")
    channels = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            cid  = row.get("channel_id", "").strip()
            name = row.get("channel_name", "").strip()
            if cid:
                channels[cid] = name
    return channels


# People responsible for responding — messages from anyone NOT in this set trigger the timer
RESPONDER_IDS: set[str] = _load_responder_ids()

# {channel_id: channel_name} — all ops channels to monitor
MONITORED_CHANNELS: dict[str, str] = _load_monitored_channels()


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _sb_headers() -> dict:
    return {
        "apikey":        SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "resolution=merge-duplicates,return=minimal",
    }


def _sb_upsert_message(row: dict) -> None:
    try:
        resp = http_requests.post(
            f"{SB_URL}/rest/v1/slack_messages",
            headers=_sb_headers(),
            json=row,
            timeout=10,
        )
        if not resp.ok:
            logger.error("Supabase upsert failed: %s %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.error("Supabase upsert error: %s", exc)


def _sb_mark_responded(channel_id: str, message_ts: str) -> None:
    try:
        http_requests.patch(
            f"{SB_URL}/rest/v1/slack_messages",
            headers={**_sb_headers(), "Prefer": "return=minimal"},
            params={"channel_id": f"eq.{channel_id}", "message_ts": f"eq.{message_ts}"},
            json={"has_response": True},
            timeout=10,
        )
    except Exception as exc:
        logger.error("Supabase mark_responded error: %s", exc)


def _sb_insert_unanswered_event(info: dict) -> None:
    try:
        http_requests.post(
            f"{SB_URL}/rest/v1/slack_unanswered_events",
            headers={**_sb_headers(), "Prefer": "return=minimal"},
            json={
                "channel_id":      info["channel"],
                "channel_name":    info.get("channel_name"),
                "message_ts":      info["slack_ts"],
                "user_id":         info.get("user"),
                "user_name":       info.get("user_name"),
                "message_text":    info.get("text", "")[:500],
                "timeout_minutes": RESPONSE_TIMEOUT_SECONDS // 60,
            },
            timeout=10,
        )
    except Exception as exc:
        logger.error("Supabase unanswered insert error: %s", exc)


def _sb_resolve_unanswered(channel_id: str, message_ts: str) -> None:
    try:
        http_requests.patch(
            f"{SB_URL}/rest/v1/slack_unanswered_events",
            headers={**_sb_headers(), "Prefer": "return=minimal"},
            params={
                "channel_id": f"eq.{channel_id}",
                "message_ts": f"eq.{message_ts}",
                "resolved":   "eq.false",
            },
            json={"resolved": True, "resolved_at": datetime.now(timezone.utc).isoformat()},
            timeout=10,
        )
    except Exception as exc:
        logger.error("Supabase resolve error: %s", exc)


# ── Slack metadata cache ──────────────────────────────────────────────────────

_user_cache: dict[str, str] = {}


def _user_name(user_id: str) -> str:
    if not user_id:
        return "unknown"
    if user_id not in _user_cache:
        try:
            resp = app.client.users_info(user=user_id)
            profile = resp["user"].get("profile", {})
            _user_cache[user_id] = (
                profile.get("display_name") or profile.get("real_name") or user_id
            )
        except Exception:
            _user_cache[user_id] = user_id
    return _user_cache[user_id]


_MENTION_RE = re.compile(r"<@([A-Z0-9]+)>")


def _resolve_mentions(text: str) -> str:
    """Replace <@USERID> tokens with @display_name."""
    return _MENTION_RE.sub(lambda m: f"@{_user_name(m.group(1))}", text)


# ── Unanswered tracking ───────────────────────────────────────────────────────
# Key: (channel_id, message_ts) — only non-responder messages are tracked.

pending: dict[tuple[str, str], dict] = {}
pending_lock = threading.Lock()


def _cancel_channel_pending(channel_id: str, responder_id: str) -> None:
    """A responder replied — cancel pending items where they were @mentioned."""
    cancelled = []
    with pending_lock:
        for key in list(pending.keys()):
            if key[0] == channel_id and responder_id in pending[key].get("mentioned_responders", set()):
                cancelled.append(pending.pop(key))

    for info in cancelled:
        logger.info(
            "Resolved: %s in %s (@%s replied)", info["slack_ts"], channel_id, responder_id
        )
        threading.Thread(
            target=lambda i=info: (
                _sb_mark_responded(i["channel"], i["slack_ts"]),
                _sb_resolve_unanswered(i["channel"], i["slack_ts"]),
            ),
            daemon=True,
        ).start()


@app.event("message")
def handle_message(event, logger):
    if event.get("subtype") or event.get("bot_id"):
        return

    channel_id = event.get("channel")
    if channel_id not in MONITORED_CHANNELS:
        return

    user_id    = event.get("user", "")
    message_ts = event.get("ts")
    thread_ts  = event.get("thread_ts")
    is_reply   = bool(thread_ts and thread_ts != message_ts)
    is_responder = user_id in RESPONDER_IDS

    # ── Store every message to Supabase ───────────────────────────────────────
    def _store():
        row = {
            "channel_id":      channel_id,
            "channel_name":    MONITORED_CHANNELS.get(channel_id, channel_id),
            "message_ts":      message_ts,
            "thread_ts":       thread_ts if is_reply else None,
            "is_thread_reply": is_reply,
            "user_id":         user_id,
            "user_name":       _user_name(user_id),
            "text":            _resolve_mentions(event.get("text") or ""),
            "has_response":    is_responder,
            "created_at":      datetime.fromtimestamp(
                                   float(message_ts), tz=timezone.utc
                               ).isoformat(),
        }
        _sb_upsert_message(row)

    threading.Thread(target=_store, daemon=True).start()

    # ── Alert logic ───────────────────────────────────────────────────────────
    text = event.get("text") or ""

    if is_responder:
        # A Savvy staff member replied — cancel pending items where they were tagged
        channel_name = MONITORED_CHANNELS.get(channel_id, channel_id)
        logger.info("Staff reply from %s in #%s (thread: %s)", user_id, channel_name, thread_ts or "none")
        if any(k[0] == channel_id for k in pending):
            _cancel_channel_pending(channel_id, user_id)
        else:
            logger.info("No pending items in #%s to cancel", channel_name)
    else:
        # A non-staff (client) sent a message — only track if a staff member is @mentioned
        mentioned_responders = set(_MENTION_RE.findall(text)) & RESPONDER_IDS
        if not mentioned_responders:
            return

        if "thank" in text.lower():
            return

        is_open, is_weekend = _business_hours_status()

        if is_weekend:
            try:
                app.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=message_ts,
                    text=WEEKEND_AUTO_REPLY,
                )
                logger.info("Sent weekend auto-reply in #%s", MONITORED_CHANNELS.get(channel_id, channel_id))
            except Exception as exc:
                logger.error("Failed to send weekend auto-reply: %s", exc)
            return

        if not is_open:
            logger.info("Outside business hours — not tracking message %s", message_ts)
            return

        # Within business hours — start tracking
        channel_name = MONITORED_CHANNELS.get(channel_id, channel_id)
        with pending_lock:
            pending[(channel_id, message_ts)] = {
                "channel":             channel_id,
                "channel_name":        channel_name,
                "slack_ts":            message_ts,
                "float_ts":            float(message_ts),
                "user":                user_id,
                "text":                text[:500],
                "mentioned_responders": mentioned_responders,
            }
        logger.info(
            "Tracking message %s in #%s — tagged staff: %s (timeout: %d min)",
            message_ts, channel_name, mentioned_responders, RESPONSE_TIMEOUT_SECONDS // 60,
        )


@app.action(re.compile(".*"))
def handle_any_action(ack):
    ack()


@app.event("reaction_added")
def handle_reaction_added(body):
    event = body.get("event", {})
    item = event.get("item", {})
    if item.get("type") != "message":
        return
    channel_id = item.get("channel")
    message_ts = item.get("ts")
    item_user  = event.get("item_user")  # sender of the message that was reacted to
    reaction_float = float(message_ts)

    resolved = []
    with pending_lock:
        for key in list(pending.keys()):
            if key[0] != channel_id:
                continue
            info = pending[key]
            # Exact match OR: reaction is on a later message from the same client
            if key[1] == message_ts or (
                item_user and info.get("user") == item_user and reaction_float >= info["float_ts"]
            ):
                resolved.append(pending.pop(key))

    for info in resolved:
        logger.info("Resolved via reaction: %s in %s", info["slack_ts"], channel_id)
        threading.Thread(
            target=lambda i=info: (
                _sb_mark_responded(i["channel"], i["slack_ts"]),
                _sb_resolve_unanswered(i["channel"], i["slack_ts"]),
            ),
            daemon=True,
        ).start()


# ── Alert sending ─────────────────────────────────────────────────────────────

def _send_alert(info: dict) -> None:
    channel_id   = info["channel"]
    channel_name = info.get("channel_name", channel_id)
    slack_ts     = info["slack_ts"]
    timeout_min  = RESPONSE_TIMEOUT_SECONDS // 60
    try:
        permalink = app.client.chat_getPermalink(channel=channel_id, message_ts=slack_ts)["permalink"]
    except Exception:
        permalink = f"https://slack.com/archives/{channel_id}/p{slack_ts.replace('.', '')}"
    raw_text     = info["text"] or ""
    preview      = _resolve_mentions(raw_text) or "(no text)"
    info.setdefault("user_name", _user_name(info.get("user", "")))
    mentioned_responders = info.get("mentioned_responders", set())

    fallback = f":warning: No response after {timeout_min} minutes: \"{preview}\" {permalink}"

    try:
        app.client.chat_postMessage(
            channel=ALERT_CHANNEL_ID,
            text=fallback,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":warning: No response after *{timeout_min} minutes*:\n\"{preview}\"",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": "view_unanswered_message",
                            "text": {"type": "plain_text", "text": "View message"},
                            "url": permalink,
                        }
                    ],
                },
            ],
        )
        logger.info("Alert sent in #%s for %s", channel_name, slack_ts)
    except Exception as exc:
        logger.error("Failed to send alert: %s", exc)

    threading.Thread(target=_sb_insert_unanswered_event, args=(info,), daemon=True).start()


def _checker_loop() -> None:
    while True:
        time.sleep(30)
        now = time.time()
        expired = []

        with pending_lock:
            for key, info in list(pending.items()):
                if now - info["float_ts"] >= RESPONSE_TIMEOUT_SECONDS:
                    expired.append(info)
                    del pending[key]

        for info in expired:
            _send_alert(info)


if __name__ == "__main__":
    logger.info("Loaded %d responder IDs from member_directory.csv", len(RESPONDER_IDS))
    logger.info("Monitoring %d channels from ops_channels.csv", len(MONITORED_CHANNELS))
    logger.info("Alert channel   : %s", ALERT_CHANNEL_ID)
    logger.info("Response timeout: %d minutes", RESPONSE_TIMEOUT_SECONDS // 60)

    checker = threading.Thread(target=_checker_loop, daemon=True)
    checker.start()

    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()

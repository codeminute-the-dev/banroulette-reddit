import os
import json
import time
import atexit
import logging
import random
from pathlib import Path
from datetime import datetime, timezone

import praw
import praw.exceptions

from config import (
    CLIENT_ID, CLIENT_SECRET, BOT_USERNAME, BOT_PASSWORD,
    SUBREDDIT_NAME, TRIGGER_PHRASES, BAN_POOL,
    KILLSWITCH_FILE, MOD_CACHE_TTL,
    BOT_REPLY_TEMPLATE, BAN_MESSAGE_TEMPLATE,
    ALREADY_BANNED_REPLY,
)

PID_FILE    = Path("bot.pid")
STATUS_FILE = Path("bot_status.json")
RUNTIME_CFG = Path("runtime_config.json")

_session = {
    "state":      "starting",
    "pid":        os.getpid(),
    "started_at": datetime.now(timezone.utc).isoformat(),
    "bans":       0,
    "last_post":  None,
    "subreddit":  "",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("banroulette.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("banroulette")


def write_status(state=None):
    if state:
        _session["state"] = state
    try:
        STATUS_FILE.write_text(json.dumps(_session, indent=2))
    except Exception:
        pass


def _cleanup():
    write_status("stopped")
    PID_FILE.unlink(missing_ok=True)


def load_runtime_config():
    defaults = {
        "subreddit":            SUBREDDIT_NAME,
        "trigger_phrases":      TRIGGER_PHRASES,
        "ban_pool":             [{"days": d, "label": l, "weight": w} for d, l, w in BAN_POOL],
        "bot_reply_template":   BOT_REPLY_TEMPLATE,
        "ban_message_template": BAN_MESSAGE_TEMPLATE,
        "already_banned_reply": ALREADY_BANNED_REPLY,
    }
    if not RUNTIME_CFG.exists():
        return defaults
    try:
        stored = json.loads(RUNTIME_CFG.read_text())
        merged = {**defaults}
        for k, v in stored.items():
            if v or v == 0:
                merged[k] = v
        return merged
    except Exception as e:
        log.warning(f"runtime_config.json unreadable ({e}), using defaults")
        return defaults


def build_pool(pool_data):
    return [(e.get("days"), e["label"], int(e["weight"])) for e in pool_data]


def spin(pool):
    items   = [(d, l) for d, l, _ in pool]
    weights = [w      for _, _, w in pool]
    return random.choices(items, weights=weights, k=1)[0]


def killswitch_active():
    return Path(KILLSWITCH_FILE).exists()


def is_trigger(title, phrases):
    t = title.lower()
    return any(p in t for p in phrases)


def bot_has_replied(submission):
    try:
        submission.comments.replace_more(limit=0)
        for c in submission.comments.list():
            if c.author and c.author.name.lower() == BOT_USERNAME.lower():
                return True
    except Exception:
        pass
    return False


def user_is_banned(subreddit, username):
    try:
        return len(list(subreddit.banned(redditor=username))) > 0
    except praw.exceptions.Forbidden:
        return False
    except Exception:
        return False


def handle(subreddit, submission, mod_names, cfg):
    if not is_trigger(submission.title, cfg["trigger_phrases"]):
        return

    author = submission.author
    if author is None:
        return

    username = author.name
    log.info(f"hit: {submission.id} by u/{username}")

    if username.lower() in mod_names:
        return

    if bot_has_replied(submission):
        return

    if user_is_banned(subreddit, username):
        try:
            submission.reply(cfg["already_banned_reply"].format(username=username))
        except Exception:
            pass
        return

    pool = build_pool(cfg["ban_pool"])
    days, label = spin(pool)
    log.info(f"  result: {label}")

    reply_text = cfg["bot_reply_template"].format(username=username, result=f"**{label}**")
    ban_dm     = cfg["ban_message_template"].format(label=label, subreddit=cfg["subreddit"])
    mod_note   = f"Ban Roulette – {label}"

    try:
        subreddit.banned.add(username, ban_message=ban_dm, note=mod_note, duration=days)
        log.info(f"  banned u/{username}: {label}")
    except praw.exceptions.Forbidden:
        log.error("missing ban_users permission")
        return
    except Exception as e:
        log.error(f"ban failed for u/{username}: {e}")
        return

    try:
        submission.reply(reply_text)
    except praw.exceptions.APIException as e:
        log.warning(f"reply failed: {e}")

    _session["bans"] += 1
    _session["last_post"] = {
        "id":     submission.id,
        "title":  submission.title,
        "author": username,
        "result": label,
        "at":     datetime.now(timezone.utc).isoformat(),
    }
    write_status()


def run():
    log.info("starting up")

    PID_FILE.write_text(str(os.getpid()))
    atexit.register(_cleanup)
    write_status("starting")

    cfg = load_runtime_config()
    _session["subreddit"] = cfg["subreddit"]
    log.info(f"subreddit: r/{cfg['subreddit']}")

    reddit = praw.Reddit(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        username=BOT_USERNAME,
        password=BOT_PASSWORD,
        user_agent=f"BanRouletteBot/1.0 by u/{BOT_USERNAME}",
    )

    sub = reddit.subreddit(cfg["subreddit"])
    write_status("running")

    mod_names    = []
    mod_cache_ts = 0.0

    while True:
        if killswitch_active():
            log.warning("killswitch active, shutting down")
            break

        try:
            now = time.time()
            if now - mod_cache_ts > MOD_CACHE_TTL:
                mod_names    = [m.name.lower() for m in sub.moderator()]
                mod_cache_ts = now
                log.info(f"mod list refreshed ({len(mod_names)})")

            for submission in sub.stream.submissions(skip_existing=True):
                if killswitch_active():
                    log.warning("killswitch mid-stream, exiting")
                    return

                if submission is None:
                    continue

                now = time.time()
                if now - mod_cache_ts > MOD_CACHE_TTL:
                    mod_names    = [m.name.lower() for m in sub.moderator()]
                    mod_cache_ts = now

                handle(sub, submission, mod_names, cfg)

        except praw.exceptions.APIException as e:
            log.error(f"api error: {e}, retry in 60s")
            time.sleep(60)
        except Exception as e:
            log.error(f"crash: {e}, reconnect in 30s")
            time.sleep(30)


if __name__ == "__main__":
    run()

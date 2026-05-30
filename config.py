import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID     = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
BOT_USERNAME  = os.getenv("BOT_USERNAME", "")
BOT_PASSWORD  = os.getenv("BOT_PASSWORD", "")

SUBREDDIT_NAME = os.getenv("SUBREDDIT", "test")

TRIGGER_PHRASES = [
    "play ban roulette",
]

# (days, label, weight) — days=None is permanent, higher weight = rolled more often
BAN_POOL = [
    (1,    "1 day",        20),
    (3,    "3 days",       18),
    (7,    "1 week",       15),
    (14,   "2 weeks",      12),
    (30,   "30 days",      10),
    (60,   "2 months",      8),
    (90,   "3 months",      7),
    (180,  "6 months",      5),
    (365,  "1 year",        3),
]

MOD_CACHE_TTL = 300

KILLSWITCH_FILE = "KILLSWITCH"

BOT_REPLY_TEMPLATE = """\
**Ban Roulette Result**

u/{username} spun the wheel...

**Result: {result}**

*The wheel has spoken. No take-backsies.*

---
^(Self-requested via Ban Roulette · Contact mods if you think this is wrong)"""

BAN_MESSAGE_TEMPLATE = """\
You played Ban Roulette on r/{subreddit} and landed on: **{label}**.

This was self-requested. Sit tight."""

ALREADY_BANNED_REPLY = (
    "u/{username} you're already banned here lol. Come back when you're out. "
)

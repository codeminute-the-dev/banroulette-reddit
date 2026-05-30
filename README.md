# ban-roulette-bot

Users opt in by putting "play ban roulette" anywhere in their post title. Bot detects it, picks a random ban duration, bans them, and replies with the result.

## Setup

**1. Create a Reddit script app**

Log into the bot account → https://www.reddit.com/prefs/apps → create app → type: script. Grab the client ID and secret.

**2. Add the bot as a mod**

Subreddit mod tools → Moderators → invite the bot account with `Ban users` permission only.

**3. Install**

```
pip install -r requirements.txt
cp .env.example .env
# fill in .env
```

**4. Run**

Start the admin panel:
```
python admin.py
```
Open http://localhost:5000, configure everything, then hit START. That's it.

Or run the bot directly without the admin panel:
```
python bot.py
```

## Admin panel

- **START / STOP / RESTART** — process control
- **KILLSWITCH** — same as creating a KILLSWITCH file manually, stops the bot cleanly
- **CONFIG tab** — edit subreddit, trigger phrases, ban pool, message templates (saved to `runtime_config.json`, takes effect on restart)
- **LOGS tab** — live tail of `banroulette.log`

Password is set via `ADMIN_PASSWORD` in `.env`.

## Manual killswitch

If you're not using the admin panel, create a file named `KILLSWITCH` in the bot directory:

```bash
touch KILLSWITCH          # linux/mac
echo. > KILLSWITCH        # windows cmd
```

Bot checks for this file on every iteration and exits cleanly. Delete it before restarting.

## Notes

- Reddit API minimum temp ban duration is 1 day, so sub-day bans aren't possible
- Mods are never banned regardless of what they post
- Bot won't double-process a post if it restarts mid-run — it checks for its own existing reply first
- All settings in `config.py` are the defaults; `runtime_config.json` (written by the admin panel) overrides them at startup

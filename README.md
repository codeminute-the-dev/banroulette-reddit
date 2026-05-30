# ban-roulette

bans redditors when they ask for it. that's it.

wrote this because people like gambling. (jk, some discord user asked me for it and i agreed cause funny)

![platform](https://img.shields.io/badge/platform-reddit-ff4500)
![language](https://img.shields.io/badge/language-python-3776ab)
![license](https://img.shields.io/badge/license-MIT-green)

---

## what it does

- detects when someone puts a trigger phrase (like "play ban roulette") in a post title
- rolls a weighted virtual wheel for a ban duration
- bans them, replies to the post, sends a dm. pretty straightforward
- has a web admin panel if you don't like editing json files
- ignores mods (obviously)
---

## setup

needs a reddit script app. go to your bot account's prefs/apps, make one, grab the client id and secret. invite the bot to your sub with `Ban users` permission only.

```bat
pip install -r requirements.txt
cp .env.example .env
```

fill out the `.env`. no docker container. no poetry. no 47-step setup.

---

## usage

run the admin panel:

```bat
python admin.py
```

go to `http://localhost:5000`. log in (default password is in the code, you will want to change it in `.env`), set your subreddit and trigger phrases, and hit start.

if you hate web uis, just run the bot directly:

```bat
python bot.py
```

---

## output

if you're tailing `banroulette.log` or looking at the web panel logs:

```
  2026-05-30 12:34:56  INFO      hit: x1y2z3 by u/someguy
  2026-05-30 12:34:56  INFO        result: 30 days
  2026-05-30 12:34:57  INFO        banned u/someguy: 30 days
  2026-05-30 12:40:12  INFO      hit: a9b8c7 by u/alreadybannedguy
```

good for when you're staring at it at 2am watching people voluntarily ruin their own subreddit access.

---

## caveats

- reddit api minimum temp ban is 1 day. you can't ban someone for 5 minutes
- if you run it headless and want to stop it cleanly, make a file called `KILLSWITCH` in the bot directory. delete it before restarting
- it won't double-process a post if it crashes mid-run, it checks for its own existing reply first

---

## license

idc, do whatever you want with it

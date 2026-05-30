import os
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone

import psutil
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("ADMIN_SECRET", os.urandom(24).hex())

ADMIN_PASSWORD  = os.getenv("ADMIN_PASSWORD", "admin")
ADMIN_PORT      = int(os.getenv("ADMIN_PORT", 5000))

BOT_SCRIPT      = Path("bot.py")
KILLSWITCH_FILE = Path("KILLSWITCH")
PID_FILE        = Path("bot.pid")
STATUS_FILE     = Path("bot_status.json")
LOG_FILE        = Path("banroulette.log")
RUNTIME_CFG     = Path("runtime_config.json")
LOG_TAIL        = 150

try:
    from config import (
        BOT_REPLY_TEMPLATE, BAN_MESSAGE_TEMPLATE, ALREADY_BANNED_REPLY,
        SUBREDDIT_NAME, TRIGGER_PHRASES, BAN_POOL
    )
    _default_pool = [{"days": d, "label": l, "weight": w} for d, l, w in BAN_POOL]
    _default_sub  = os.getenv("SUBREDDIT", "") or SUBREDDIT_NAME
except ImportError:
    BOT_REPLY_TEMPLATE = BAN_MESSAGE_TEMPLATE = ALREADY_BANNED_REPLY = ""
    _default_sub = os.getenv("SUBREDDIT", "")
    TRIGGER_PHRASES = ["play ban roulette"]
    _default_pool = [
        {"days": 1,    "label": "1 day",    "weight": 20},
        {"days": 3,    "label": "3 days",   "weight": 18},
        {"days": 7,    "label": "1 week",   "weight": 15},
        {"days": 14,   "label": "2 weeks",  "weight": 12},
        {"days": 30,   "label": "30 days",  "weight": 10},
        {"days": 60,   "label": "2 months", "weight":  8},
        {"days": 90,   "label": "3 months", "weight":  7},
        {"days": 180,  "label": "6 months", "weight":  5},
        {"days": 365,  "label": "1 year",   "weight":  3},
    ]

DEFAULT_CONFIG = {
    "subreddit":            _default_sub,
    "trigger_phrases":      TRIGGER_PHRASES,
    "ban_pool":             _default_pool,
    "bot_reply_template":   BOT_REPLY_TEMPLATE,
    "ban_message_template": BAN_MESSAGE_TEMPLATE,
    "already_banned_reply": ALREADY_BANNED_REPLY,
}


def get_bot_pid():
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def is_bot_running():
    pid = get_bot_pid()
    if pid is None:
        return False
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def get_status():
    try:
        data = json.loads(STATUS_FILE.read_text())
    except Exception:
        data = {}
    data["running"]    = is_bot_running()
    data["killswitch"] = KILLSWITCH_FILE.exists()
    return data


def start_bot():
    if is_bot_running():
        return False, "Already running."
    KILLSWITCH_FILE.unlink(missing_ok=True)
    subprocess.Popen(
        [sys.executable, str(BOT_SCRIPT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.8)
    return True, "Bot started."


def stop_bot():
    if not is_bot_running():
        return False, "Not running."
    KILLSWITCH_FILE.touch()
    return True, "Killswitch set, bot stopping."


def restart_bot():
    KILLSWITCH_FILE.touch()
    for _ in range(20):
        time.sleep(0.5)
        if not is_bot_running():
            break
    KILLSWITCH_FILE.unlink(missing_ok=True)
    subprocess.Popen(
        [sys.executable, str(BOT_SCRIPT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.8)
    return True, "Bot restarted."


def load_config():
    if not RUNTIME_CFG.exists():
        return dict(DEFAULT_CONFIG)
    try:
        stored = json.loads(RUNTIME_CFG.read_text())
        merged = dict(DEFAULT_CONFIG)
        for k, v in stored.items():
            if v or v == 0:
                merged[k] = v
        return merged
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(data):
    RUNTIME_CFG.write_text(json.dumps(data, indent=2))


def tail_log(n=LOG_TAIL):
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception:
        return ["(log not found)"]


def fmt_uptime(iso):
    if not iso:
        return "—"
    try:
        started = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        s = int((datetime.now(timezone.utc) - started).total_seconds())
        if s < 60:   return f"{s}s"
        if s < 3600: return f"{s//60}m {s%60}s"
        return f"{s//3600}h {(s%3600)//60}m"
    except Exception:
        return "—"


def authed():
    return session.get("auth") == "ok"


@app.route("/login", methods=["GET", "POST"])
def login():
    err = ""
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["auth"] = "ok"
            return redirect(url_for("dashboard"))
        err = "Wrong password."
    return render_template_string(LOGIN_HTML, error=err)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    if not authed():
        return redirect(url_for("login"))
    return render_template_string(DASHBOARD_HTML, cfg=load_config())


@app.route("/api/status")
def api_status():
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    s = get_status()
    s["uptime"] = fmt_uptime(s.get("started_at"))
    return jsonify(s)


@app.route("/api/logs")
def api_logs():
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"lines": tail_log()})


@app.route("/api/control", methods=["POST"])
def api_control():
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    action = request.json.get("action", "")
    if   action == "start":         ok, msg = start_bot()
    elif action == "stop":          ok, msg = stop_bot()
    elif action == "restart":       ok, msg = restart_bot()
    elif action == "killswitch_on":
        KILLSWITCH_FILE.touch()
        ok, msg = True, "Killswitch on."
    elif action == "killswitch_off":
        KILLSWITCH_FILE.unlink(missing_ok=True)
        ok, msg = True, "Killswitch off."
    else:
        return jsonify({"ok": False, "msg": f"unknown action: {action}"}), 400
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/config", methods=["GET"])
def api_config_get():
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(load_config())


@app.route("/api/config", methods=["POST"])
def api_config_save():
    if not authed():
        return jsonify({"error": "unauthorized"}), 401
    data = request.json
    if not data:
        return jsonify({"ok": False, "msg": "empty payload"}), 400
    if not data.get("subreddit", "").strip():
        return jsonify({"ok": False, "msg": "subreddit can't be empty"}), 400
    pool = data.get("ban_pool", [])
    if not pool:
        return jsonify({"ok": False, "msg": "ban pool can't be empty"}), 400
    for row in pool:
        if not str(row.get("label", "")).strip():
            return jsonify({"ok": False, "msg": "every row needs a label"}), 400
        try:
            if int(row.get("weight", 0)) < 1:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({"ok": False, "msg": f"bad weight: {row.get('weight')}"}), 400
    save_config(data)
    return jsonify({"ok": True, "msg": "saved — restart bot to apply"})


LOGIN_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Ban Roulette</title>
  <style>
    :root{--bg:#11111b;--s:#1e1e2e;--b:#313244;--tx:#cdd6f4;--mu:#585b70;--mv:#cba6f7;--re:#f38ba8}
    *{box-sizing:border-box;margin:0;padding:0}
    body{background:var(--bg);color:var(--tx);font-family:'Cascadia Code','JetBrains Mono',ui-monospace,monospace;font-size:13px;min-height:100vh;display:flex;align-items:center;justify-content:center}
    .box{background:var(--s);border:1px solid var(--b);border-radius:8px;padding:36px 32px;width:300px;display:flex;flex-direction:column;gap:14px}
    h2{text-align:center;font-size:14px;letter-spacing:3px;color:var(--mv)}
    .sub{text-align:center;font-size:11px;color:var(--mu)}
    input{width:100%;background:var(--bg);border:1px solid var(--b);border-radius:4px;color:var(--tx);font-family:inherit;font-size:12px;padding:10px 12px;outline:none}
    input:focus{border-color:var(--mv)}
    button{width:100%;background:none;border:1px solid var(--mv);border-radius:4px;color:var(--mv);font-family:inherit;font-size:12px;letter-spacing:1px;padding:10px;cursor:pointer}
    button:hover{background:rgba(203,166,247,.1)}
    .err{color:var(--re);font-size:11px;text-align:center}
  </style>
</head>
<body>
  <div class="box">
    <h2>BAN ROULETTE</h2>
    <div class="sub">admin panel</div>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
    <form method="POST">
      <input type="password" name="password" placeholder="password" autofocus>
      <br><br>
      <button type="submit">ENTER</button>
    </form>
  </div>
</body>
</html>"""


DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Ban Roulette Admin</title>
  <style>
    :root{
      --bg:#11111b;--mantle:#181825;--s:#1e1e2e;
      --s0:#313244;--s1:#45475a;
      --tx:#cdd6f4;--sub:#a6adc8;--mu:#585b70;
      --green:#a6e3a1;--red:#f38ba8;--yellow:#f9e2af;
      --blue:#89b4fa;--mv:#cba6f7;--teal:#94e2d5;
    }
    *{box-sizing:border-box;margin:0;padding:0}
    body{background:var(--bg);color:var(--tx);font-family:'Cascadia Code','JetBrains Mono','Fira Code',ui-monospace,monospace;font-size:13px;min-height:100vh}
    header{background:var(--mantle);border-bottom:1px solid var(--s0);padding:0 24px;height:52px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}
    .logo{font-size:15px;font-weight:700;letter-spacing:3px;color:var(--mv)}
    .hdr-r{display:flex;align-items:center;gap:12px}
    .badge{padding:3px 10px;border-radius:99px;font-size:10px;font-weight:700;letter-spacing:1px}
    .badge.running{background:#1a3a28;color:var(--green);border:1px solid #2a5a3a}
    .badge.stopped{background:#3a1a28;color:var(--red);border:1px solid #5a2a3a}
    .badge.unknown{background:var(--s0);color:var(--sub);border:1px solid var(--s1)}
    .ks-warn{font-size:10px;color:var(--red);letter-spacing:1px;display:none}
    .ks-warn.on{display:block}
    a.out{font-size:11px;color:var(--mu);text-decoration:none}
    a.out:hover{color:var(--sub)}
    main{max-width:1000px;margin:0 auto;padding:24px}
    .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--s0);border:1px solid var(--s0);border-radius:6px;overflow:hidden;margin-bottom:16px}
    .stat{background:var(--mantle);padding:12px 16px;display:flex;flex-direction:column;gap:4px}
    .stat .lbl{font-size:10px;letter-spacing:1px;color:var(--mu)}
    .stat .val{font-size:16px}
    .controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}
    button{background:var(--s);color:var(--tx);border:1px solid var(--s1);border-radius:4px;padding:8px 16px;cursor:pointer;font-family:inherit;font-size:11px;letter-spacing:1px;transition:background .1s}
    button:hover{background:var(--s0)}
    button:disabled{opacity:.4;cursor:not-allowed}
    .btn-start{border-color:var(--green);color:var(--green)}
    .btn-start:hover{background:#1a3a28}
    .btn-stop{border-color:var(--red);color:var(--red)}
    .btn-stop:hover{background:#3a1a28}
    .btn-restart{border-color:var(--yellow);color:var(--yellow)}
    .btn-restart:hover{background:#3a2e18}
    .btn-ks{border-color:var(--red);color:var(--red);font-weight:700}
    .btn-ks.on{background:var(--red);color:var(--bg)}
    .btn-save{border-color:var(--blue);color:var(--blue)}
    .btn-save:hover{background:#1a2a3a}
    .btn-add{border-color:var(--teal);color:var(--teal);font-size:11px;padding:6px 12px}
    .btn-add:hover{background:#1a2a2a}
    .btn-del{border-color:var(--red);color:var(--red);padding:4px 8px;font-size:11px}
    .tabs{display:flex;border-bottom:1px solid var(--s0);margin-bottom:20px}
    .tab{background:none;border:none;border-bottom:2px solid transparent;border-radius:0;padding:9px 20px;color:var(--mu);letter-spacing:1px;font-size:11px;margin-bottom:-1px;cursor:pointer;font-family:inherit}
    .tab:hover{color:var(--sub);background:none}
    .tab.active{color:var(--mv);border-bottom-color:var(--mv)}
    .pane{display:none}
    .pane.active{display:block}
    .sec{background:var(--mantle);border:1px solid var(--s0);border-radius:6px;padding:16px;margin-bottom:14px}
    .sec h3{font-size:10px;letter-spacing:2px;color:var(--mv);margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--s0)}
    .row{display:flex;align-items:center;gap:10px;margin-bottom:8px}
    .lbl{font-size:11px;color:var(--sub);min-width:90px}
    input[type=text],input[type=number],textarea{background:var(--bg);border:1px solid var(--s1);border-radius:4px;color:var(--tx);font-family:inherit;font-size:12px;padding:6px 10px;outline:none;transition:border-color .1s}
    input[type=text]:focus,input[type=number]:focus,textarea:focus{border-color:var(--mv)}
    .full{width:100%}
    textarea.full{resize:vertical;min-height:80px}
    .note{font-size:10px;color:var(--mu);margin-top:4px}
    .tr-list{display:flex;flex-direction:column;gap:6px}
    .tr-row{display:flex;gap:6px}
    .tr-row input{flex:1}
    .pool-wrap{overflow-x:auto}
    table{width:100%;border-collapse:collapse}
    th{text-align:left;font-size:10px;letter-spacing:1px;color:var(--mu);padding:6px 8px;border-bottom:1px solid var(--s0)}
    td{padding:4px 4px;vertical-align:middle}
    td input[type=number]{width:62px}
    td input[type=text]{width:100px}
    td input[type=checkbox]{accent-color:var(--mv);width:14px;height:14px;cursor:pointer}
    tr:hover td{background:rgba(255,255,255,.015)}
    .log-viewer{background:var(--mantle);border:1px solid var(--s0);border-radius:6px;padding:12px 16px;font-size:11px;line-height:1.8;max-height:560px;overflow-y:auto;color:var(--sub)}
    .log-ctrl{display:flex;gap:8px;align-items:center;margin-bottom:10px}
    .l-warn{color:var(--yellow)}
    .l-err{color:var(--red)}
    #toast{position:fixed;bottom:24px;right:24px;padding:10px 16px;border-radius:6px;font-size:12px;opacity:0;transition:opacity .25s;pointer-events:none;z-index:999}
    #toast.show{opacity:1}
    #toast.ok{background:#1a3a28;color:var(--green);border:1px solid #2a5a3a}
    #toast.err{background:#3a1a28;color:var(--red);border:1px solid #5a2a3a}
    #toast.inf{background:var(--s0);color:var(--blue);border:1px solid var(--s1)}
  </style>
</head>
<body>

<header>
  <div class="logo">BAN ROULETTE</div>
  <div class="hdr-r">
    <span class="ks-warn" id="ks-label">⚠ KILLSWITCH ON</span>
    <span class="badge unknown" id="status-badge">● UNKNOWN</span>
    <a href="/logout" class="out">logout</a>
  </div>
</header>

<main>

  <div class="stats">
    <div class="stat"><span class="lbl">UPTIME</span><span class="val" id="s-uptime">—</span></div>
    <div class="stat"><span class="lbl">BANS THIS SESSION</span><span class="val" id="s-bans">—</span></div>
    <div class="stat"><span class="lbl">LAST BAN</span><span class="val" id="s-last" style="font-size:12px">—</span></div>
    <div class="stat"><span class="lbl">SUBREDDIT</span><span class="val" id="s-sub" style="font-size:12px">—</span></div>
  </div>

  <div class="controls">
    <button class="btn-start"   onclick="ctrl('start')">▶ START</button>
    <button class="btn-stop"    onclick="ctrl('stop')">■ STOP</button>
    <button class="btn-restart" onclick="ctrl('restart')">↻ RESTART</button>
    <button class="btn-ks" id="btn-ks" onclick="toggleKs()">KILLSWITCH</button>
  </div>

  <div class="tabs">
    <button class="tab active" onclick="switchTab('config',this)">CONFIG</button>
    <button class="tab"        onclick="switchTab('logs',this)">LOGS</button>
  </div>

  <div class="pane active" id="tab-config">

    <div class="sec">
      <h3>SUBREDDIT</h3>
      <div class="row">
        <span class="lbl">r/</span>
        <input type="text" id="cfg-sub" class="full" value="{{ cfg.subreddit }}" placeholder="your_subreddit">
      </div>
    </div>

    <div class="sec">
      <h3>TRIGGER PHRASES</h3>
      <p class="note" style="margin-bottom:10px">Case-insensitive. Any match in post title triggers the bot.</p>
      <div class="tr-list" id="tr-list">
        {% for phrase in cfg.trigger_phrases %}
        <div class="tr-row">
          <input type="text" value="{{ phrase }}" placeholder="phrase">
          <button class="btn-del" onclick="delTr(this)">x</button>
        </div>
        {% endfor %}
      </div>
      <br>
      <button class="btn-add" onclick="addTr()">+ ADD</button>
    </div>

    <div class="sec">
      <h3>BAN POOL</h3>
      <p class="note" style="margin-bottom:10px">Higher weight = more likely. Reddit min for temp bans is 1 day.</p>
      <div class="pool-wrap">
        <table>
          <thead><tr><th>DAYS</th><th>LABEL</th><th>WEIGHT</th><th>PERMANENT</th><th></th></tr></thead>
          <tbody id="pool-body">
            {% for row in cfg.ban_pool %}
            <tr>
              <td><input type="number" class="p-days" min="1" max="999" value="{{ row.days if row.days is not none else '' }}" {{ 'disabled' if row.days is none else '' }}></td>
              <td><input type="text" class="p-label" value="{{ row.label }}"></td>
              <td><input type="number" class="p-weight" min="1" value="{{ row.weight }}"></td>
              <td style="text-align:center"><input type="checkbox" class="p-perma" onchange="togglePerma(this)" {{ 'checked' if row.days is none else '' }}></td>
              <td><button class="btn-del" onclick="delRow(this)">x</button></td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      <br>
      <button class="btn-add" onclick="addRow()">+ ADD ROW</button>
    </div>

    <div class="sec">
      <h3>BOT REPLY TEMPLATE</h3>
      <p class="note" style="margin-bottom:10px">Posted as reply to the triggering post. Vars: <code>{username}</code> <code>{result}</code></p>
      <textarea class="full" id="cfg-reply" rows="7">{{ cfg.bot_reply_template }}</textarea>
    </div>

    <div class="sec">
      <h3>BAN DM TEMPLATE</h3>
      <p class="note" style="margin-bottom:10px">Sent to banned user. Vars: <code>{label}</code> <code>{subreddit}</code></p>
      <textarea class="full" id="cfg-ban-dm" rows="5">{{ cfg.ban_message_template }}</textarea>
    </div>

    <div class="sec">
      <h3>ALREADY-BANNED REPLY</h3>
      <p class="note" style="margin-bottom:10px">Shown when an already-banned user spins. Var: <code>{username}</code></p>
      <input type="text" class="full" id="cfg-banned-r" value="{{ cfg.already_banned_reply }}">
    </div>

    <div style="display:flex;gap:12px;align-items:center">
      <button class="btn-save" onclick="saveConfig()">SAVE CONFIG</button>
      <span class="note" style="margin:0">Takes effect on next start / restart.</span>
    </div>

  </div>

  <div class="pane" id="tab-logs">
    <div class="log-ctrl">
      <button onclick="fetchLogs()">↻ REFRESH</button>
      <label style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--sub);cursor:pointer">
        <input type="checkbox" id="auto-scroll" checked style="accent-color:var(--mv)"> auto-scroll
      </label>
      <label style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--sub);cursor:pointer">
        <input type="checkbox" id="auto-refresh" checked style="accent-color:var(--mv)"> auto-refresh (5s)
      </label>
    </div>
    <div class="log-viewer" id="log-viewer"><span style="color:var(--mu)">loading...</span></div>
  </div>

</main>

<div id="toast"></div>

<script>
let _tt;
function toast(msg, t='inf') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show ' + t;
  clearTimeout(_tt);
  _tt = setTimeout(() => el.className = '', 3500);
}

function switchTab(name, btn) {
  document.querySelectorAll('.pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
  if (name === 'logs') fetchLogs();
}

async function fetchStatus() {
  try {
    const s = await (await fetch('/api/status')).json();
    const badge = document.getElementById('status-badge');
    const ksw   = document.getElementById('ks-label');
    const ksb   = document.getElementById('btn-ks');
    badge.textContent = s.running ? '● RUNNING' : '■ STOPPED';
    badge.className   = 'badge ' + (s.running ? 'running' : 'stopped');
    if (s.killswitch) { ksw.classList.add('on'); ksb.classList.add('on'); ksb.textContent = 'KILLSWITCH: ON'; }
    else              { ksw.classList.remove('on'); ksb.classList.remove('on'); ksb.textContent = 'KILLSWITCH'; }
    document.getElementById('s-uptime').textContent = s.running ? (s.uptime || '—') : '—';
    document.getElementById('s-bans').textContent   = s.bans ?? '—';
    if (s.last_post) document.getElementById('s-last').textContent = `u/${s.last_post.author} → ${s.last_post.result}`;
    document.getElementById('s-sub').textContent = s.subreddit || document.getElementById('cfg-sub')?.value || '—';
  } catch(e) {}
}
setInterval(fetchStatus, 3000);
fetchStatus();

async function ctrl(action) {
  toast({start:'Starting...',stop:'Stopping...',restart:'Restarting...'}[action] || action, 'inf');
  try {
    const d = await (await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})})).json();
    toast(d.msg, d.ok ? 'ok' : 'err');
    setTimeout(fetchStatus, 1000);
  } catch(e) { toast('request failed','err'); }
}

async function toggleKs() {
  await ctrl(document.getElementById('btn-ks').classList.contains('on') ? 'killswitch_off' : 'killswitch_on');
}

function addTr() {
  const d = document.createElement('div');
  d.className = 'tr-row';
  d.innerHTML = '<input type="text" placeholder="phrase"><button class="btn-del" onclick="delTr(this)">x</button>';
  document.getElementById('tr-list').appendChild(d);
  d.querySelector('input').focus();
}
function delTr(btn) {
  if (document.querySelectorAll('.tr-row').length > 1) btn.closest('.tr-row').remove();
  else toast('need at least one trigger','err');
}

function addRow() {
  const tr = document.createElement('tr');
  tr.innerHTML = `<td><input type="number" class="p-days" min="1" max="999" value="1"></td><td><input type="text" class="p-label" value="New Entry"></td><td><input type="number" class="p-weight" min="1" value="5"></td><td style="text-align:center"><input type="checkbox" class="p-perma" onchange="togglePerma(this)"></td><td><button class="btn-del" onclick="delRow(this)">x</button></td>`;
  document.getElementById('pool-body').appendChild(tr);
}
function delRow(btn) {
  if (document.querySelectorAll('#pool-body tr').length > 1) btn.closest('tr').remove();
  else toast('need at least one row','err');
}
function togglePerma(cb) {
  const d = cb.closest('tr').querySelector('.p-days');
  d.disabled = cb.checked;
  if (cb.checked) d.value = '';
}

async function saveConfig() {
  const sub = document.getElementById('cfg-sub').value.trim().replace(/^r\\//, '');
  if (!sub) { toast('subreddit required','err'); return; }
  const triggers = Array.from(document.querySelectorAll('.tr-row input')).map(i => i.value.trim().toLowerCase()).filter(Boolean);
  if (!triggers.length) { toast('need at least one trigger','err'); return; }
  const rows = Array.from(document.querySelectorAll('#pool-body tr'));
  const ban_pool = [];
  for (const tr of rows) {
    const perma  = tr.querySelector('.p-perma').checked;
    const label  = tr.querySelector('.p-label').value.trim();
    const weight = parseInt(tr.querySelector('.p-weight').value, 10);
    const days   = perma ? null : (parseInt(tr.querySelector('.p-days').value, 10) || 1);
    if (!label) { toast('every row needs a label','err'); return; }
    if (isNaN(weight) || weight < 1) { toast('weights must be >= 1','err'); return; }
    ban_pool.push({days, label, weight});
  }
  const payload = {
    subreddit: sub, trigger_phrases: triggers, ban_pool,
    bot_reply_template:   document.getElementById('cfg-reply').value,
    ban_message_template: document.getElementById('cfg-ban-dm').value,
    already_banned_reply: document.getElementById('cfg-banned-r').value,
  };
  try {
    const d = await (await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})).json();
    toast(d.msg, d.ok ? 'ok' : 'err');
  } catch(e) { toast('save failed','err'); }
}

function levelClass(l) {
  if (l.includes(' ERROR    ')) return 'l-err';
  if (l.includes(' WARNING  ')) return 'l-warn';
  return '';
}
function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
async function fetchLogs() {
  try {
    const d = await (await fetch('/api/logs')).json();
    const v = document.getElementById('log-viewer');
    v.innerHTML = d.lines.map(l => `<div class="${levelClass(l)}">${esc(l)}</div>`).join('') || '<span style="color:var(--mu)">(empty)</span>';
    if (document.getElementById('auto-scroll').checked) v.scrollTop = v.scrollHeight;
  } catch(e) {}
}
setInterval(() => {
  if (document.getElementById('tab-logs').classList.contains('active') && document.getElementById('auto-refresh').checked) fetchLogs();
}, 5000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    print(f"Ban Roulette Admin  →  http://localhost:{ADMIN_PORT}")
    if ADMIN_PASSWORD == "admin":
        print("WARNING: default password in use, set ADMIN_PASSWORD in .env")
    app.run(host="0.0.0.0", port=ADMIN_PORT, debug=False)

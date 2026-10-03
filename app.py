"""
Steam Dead Ranker — Web Service + Dashboard
"""

import threading
import subprocess
import sys
import json
import time
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# ── STATE ─────────────────────────────────────────────────────────────────────
state = {
    "status": "idle",          # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "processed": 0,
    "total": 0,
    "last_game": "",
    "last_score": None,
    "sent_to_discord": False,
    "error": None,
}
state_lock = threading.Lock()

LINKS_FILE = os.environ.get("LINKS_FILE", "steam_links.txt")

def count_links():
    try:
        with open(LINKS_FILE) as f:
            return sum(1 for l in f if l.strip())
    except:
        return 0

def run_scorer():
    with state_lock:
        state["status"] = "running"
        state["started_at"] = datetime.utcnow().isoformat()
        state["finished_at"] = None
        state["processed"] = 0
        state["total"] = count_links()
        state["last_game"] = ""
        state["last_score"] = None
        state["sent_to_discord"] = False
        state["error"] = None

    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", "scorer.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:
            line = line.strip()
            print(line)
            # Parse progress lines like: [42/4878] 'Game Name' → 84.2
            if line.startswith("[") and "→" in line:
                try:
                    idx_part = line.split("]")[0].strip("[")
                    done = int(idx_part.split("/")[0])
                    game_part = line.split("'")[1] if "'" in line else ""
                    score_part = float(line.split("→")[1].strip()) if "→" in line else None
                    with state_lock:
                        state["processed"] = done
                        state["last_game"] = game_part
                        state["last_score"] = score_part
                except:
                    pass
            if "Discord" in line or "Done." in line:
                with state_lock:
                    state["sent_to_discord"] = True

        proc.wait()
        with state_lock:
            state["status"] = "done" if proc.returncode == 0 else "error"
            state["finished_at"] = datetime.utcnow().isoformat()
    except Exception as e:
        with state_lock:
            state["status"] = "error"
            state["error"] = str(e)
            state["finished_at"] = datetime.utcnow().isoformat()

# ── DASHBOARD HTML ────────────────────────────────────────────────────────────
DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Steam Dead Ranker</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0f0f13;
    color: #e0e0e0;
    font-family: 'Segoe UI', system-ui, sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 40px 20px;
  }
  h1 {
    font-size: 24px;
    font-weight: 600;
    color: #fff;
    margin-bottom: 6px;
    letter-spacing: -0.5px;
  }
  .subtitle { font-size: 13px; color: #666; margin-bottom: 40px; }
  .card {
    background: #1a1a24;
    border: 1px solid #2a2a3a;
    border-radius: 16px;
    padding: 28px 32px;
    width: 100%;
    max-width: 560px;
    margin-bottom: 16px;
  }
  .status-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 24px;
  }
  .dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .dot.idle    { background: #555; }
  .dot.running { background: #3b82f6; box-shadow: 0 0 8px #3b82f6; animation: pulse 1.2s infinite; }
  .dot.done    { background: #22c55e; }
  .dot.error   { background: #ef4444; }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
  .status-text { font-size: 15px; font-weight: 500; color: #fff; }
  .progress-bar-bg {
    background: #2a2a3a;
    border-radius: 99px;
    height: 8px;
    overflow: hidden;
    margin-bottom: 10px;
  }
  .progress-bar-fill {
    height: 100%;
    border-radius: 99px;
    background: linear-gradient(90deg, #3b82f6, #8b5cf6);
    transition: width 1s ease;
  }
  .progress-text {
    font-size: 12px;
    color: #666;
    display: flex;
    justify-content: space-between;
  }
  .stats-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-top: 24px;
  }
  .stat {
    background: #0f0f13;
    border-radius: 10px;
    padding: 14px 16px;
  }
  .stat-val { font-size: 22px; font-weight: 600; color: #fff; }
  .stat-lbl { font-size: 11px; color: #555; margin-top: 3px; }
  .last-game {
    background: #0f0f13;
    border-radius: 10px;
    padding: 14px 16px;
    margin-top: 12px;
    font-size: 12px;
    color: #888;
  }
  .last-game span { color: #e0e0e0; font-weight: 500; }
  .btn {
    display: block;
    width: 100%;
    max-width: 560px;
    padding: 14px;
    border-radius: 12px;
    border: none;
    background: #3b82f6;
    color: #fff;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s, transform 0.1s;
    text-align: center;
  }
  .btn:hover { background: #2563eb; }
  .btn:active { transform: scale(0.98); }
  .btn:disabled { background: #2a2a3a; color: #555; cursor: not-allowed; }
  .discord-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #5865f2;
    color: #fff;
    font-size: 12px;
    font-weight: 500;
    padding: 4px 10px;
    border-radius: 99px;
    margin-top: 12px;
  }
  .time-row { font-size: 12px; color: #555; margin-top: 8px; }
</style>
</head>
<body>
<h1>🎮 Steam Dead Ranker</h1>
<p class="subtitle">Ranks dead indie games by review count, solo dev status &amp; price</p>

<div class="card" id="card">
  <div class="status-row">
    <div class="dot" id="dot"></div>
    <span class="status-text" id="status-text">Loading…</span>
  </div>
  <div class="progress-bar-bg">
    <div class="progress-bar-fill" id="bar" style="width:0%"></div>
  </div>
  <div class="progress-text">
    <span id="prog-count">0 / 0 games</span>
    <span id="prog-pct">0%</span>
  </div>
  <div class="stats-grid">
    <div class="stat">
      <div class="stat-val" id="stat-processed">—</div>
      <div class="stat-lbl">Processed</div>
    </div>
    <div class="stat">
      <div class="stat-val" id="stat-remaining">—</div>
      <div class="stat-lbl">Remaining</div>
    </div>
    <div class="stat">
      <div class="stat-val" id="stat-eta">—</div>
      <div class="stat-lbl">Est. time left</div>
    </div>
    <div class="stat">
      <div class="stat-val" id="stat-elapsed">—</div>
      <div class="stat-lbl">Elapsed</div>
    </div>
  </div>
  <div class="last-game" id="last-game" style="display:none">
    Last: <span id="last-game-name"></span> → <span id="last-game-score" style="color:#3b82f6"></span>
  </div>
  <div id="discord-badge" style="display:none">
    <div class="discord-badge">✓ Results sent to Discord</div>
  </div>
  <div class="time-row" id="time-row"></div>
</div>

<button class="btn" id="run-btn" onclick="triggerRun()">▶ Run Now</button>

<script>
let startTs = null;

function fmt(secs) {
  if (!secs || secs < 0) return '—';
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  if (h > 0) return h + 'h ' + m + 'm';
  if (m > 0) return m + 'm ' + s + 's';
  return s + 's';
}

async function poll() {
  try {
    const r = await fetch('/status');
    const d = await r.json();

    const dot = document.getElementById('dot');
    const txt = document.getElementById('status-text');
    const bar = document.getElementById('bar');
    const btn = document.getElementById('run-btn');

    dot.className = 'dot ' + d.status;

    const labels = { idle: 'Idle — ready to run', running: 'Running…', done: 'Done ✓', error: 'Error' };
    txt.textContent = labels[d.status] || d.status;

    const pct = d.total > 0 ? Math.round(d.processed / d.total * 100) : 0;
    bar.style.width = pct + '%';
    document.getElementById('prog-count').textContent = d.processed.toLocaleString() + ' / ' + d.total.toLocaleString() + ' games';
    document.getElementById('prog-pct').textContent = pct + '%';
    document.getElementById('stat-processed').textContent = d.processed.toLocaleString();
    document.getElementById('stat-remaining').textContent = (d.total - d.processed).toLocaleString();

    // Elapsed
    let elapsed = null;
    if (d.started_at) {
      const start = new Date(d.started_at + 'Z');
      const end = d.finished_at ? new Date(d.finished_at + 'Z') : new Date();
      elapsed = (end - start) / 1000;
    }
    document.getElementById('stat-elapsed').textContent = fmt(elapsed);

    // ETA
    let eta = null;
    if (d.status === 'running' && elapsed && d.processed > 0) {
      const rate = d.processed / elapsed;
      eta = (d.total - d.processed) / rate;
    }
    document.getElementById('stat-eta').textContent = d.status === 'running' ? fmt(eta) : '—';

    // Last game
    if (d.last_game) {
      document.getElementById('last-game').style.display = 'block';
      document.getElementById('last-game-name').textContent = d.last_game;
      document.getElementById('last-game-score').textContent = d.last_score;
    }

    // Discord badge
    document.getElementById('discord-badge').style.display = d.sent_to_discord ? 'block' : 'none';

    // Time row
    const tr = document.getElementById('time-row');
    if (d.started_at) tr.textContent = 'Started: ' + new Date(d.started_at + 'Z').toLocaleString();

    // Button
    btn.disabled = d.status === 'running';
    btn.textContent = d.status === 'running' ? '⏳ Running…' : '▶ Run Now';

  } catch(e) {}
}

async function triggerRun() {
  document.getElementById('run-btn').disabled = true;
  await fetch('/run');
  poll();
}

poll();
setInterval(poll, 3000);
</script>
</body>
</html>"""

# ── HTTP HANDLER ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/":
            self._html(DASHBOARD)

        elif self.path == "/run":
            with state_lock:
                if state["status"] == "running":
                    self._text(200, "Already running")
                    return
            t = threading.Thread(target=run_scorer)
            t.daemon = True
            t.start()
            self._text(200, "OK — scorer started")

        elif self.path == "/status":
            with state_lock:
                self._json(dict(state))

        elif self.path == "/health":
            self._text(200, "OK")

        else:
            self._text(404, "Not found")

    def _html(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def _text(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(msg.encode())

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        print(f"{self.address_string()} {format % args}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Server on port {port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

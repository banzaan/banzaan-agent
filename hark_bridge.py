"""
hark_bridge.py: reads the X list with monitor.py every 7-10 min, keeps new posts
in pending.json, and lets Hark take them (and empty the file) with one request.

Setup on the server (inside the banzaan-agent folder, next to monitor.py):
  1) add to .env:   HARK_API_KEY=<long random string, e.g. from: openssl rand -hex 24>
  2) run:           python3 hark_bridge.py           (test; Ctrl+C to stop)
  3) HTTPS with Caddy (ports 80 and 443 open):
       caddy reverse-proxy --from 95-182-96-215.sslip.io --to localhost:8787
  4) keep both running with systemd (examples at the bottom of this file)

Endpoints (header X-API-Key: <HARK_API_KEY>):
  GET /health  -> {"pending": n, "last_ok": ..., "last_error": ...}
  GET /pop     -> {"items": [...], "last_ok": ..., "last_error": ...} and empties pending.json
"""
import json
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv

import state
from monitor import fetch_new_tweets

load_dotenv()

API_KEY = os.getenv("HARK_API_KEY", "")
PORT = int(os.getenv("HARK_BRIDGE_PORT", "8787"))
PENDING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending.json")
MIN_WAIT, MAX_WAIT = 420, 600  # seconds, same rhythm as before
TOP_N = 5  # only the newest 5 posts of the list each time

AI_WORDS = re.compile(
    r"\b(ai|a\.i\.|agi|llms?|gpts?|chatgpt|openai|anthropic|claude|gemini|deepmind|llama|mistral|"
    r"grok|xai|copilot|cursor|hugging ?face|transformers?|neural|machine learning|deep learning|"
    r"ml|rl|reinforcement|models?|agents?|agentic|inference|fine-?tun\w*|training|benchmarks?|"
    r"datasets?|tokens?|prompts?|reasoning|diffusion|multimodal|embeddings?|rag|arxiv|paper|"
    r"research|robots?|robotics|nvidia|gpus?|compute)\b",
    re.IGNORECASE,
)


def is_ai(text):
    return bool(AI_WORDS.search(text or ""))

lock = threading.Lock()
status = {"last_ok": None, "last_error": None}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_pending():
    try:
        with open(PENDING, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def write_pending(items):
    tmp = PENDING + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PENDING)


def poll_loop():
    state.init_db()
    while True:
        try:
            tweets = fetch_new_tweets()
            if tweets is None:
                status["last_error"] = f"{now()} fetch failed (cookies expired?)"
            else:
                status["last_ok"] = now()
                tweets = [t for t in tweets[-TOP_N:] if is_ai(t.text)]
                if tweets:
                    with lock:
                        items = read_pending()
                        for t in tweets:
                            items.append({
                                "id": t.tweet_id,
                                "author": t.author,
                                "url": f"https://x.com/{t.author}/status/{t.tweet_id}",
                                "text": t.text,
                                "found_at": now(),
                            })
                        write_pending(items)
        except Exception as e:
            status["last_error"] = f"{now()} {e}"
        time.sleep(random.randint(MIN_WAIT, MAX_WAIT))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not API_KEY or self.headers.get("X-API-Key") != API_KEY:
            return self._send(401, {"error": "unauthorized"})
        if self.path == "/health":
            with lock:
                n = len(read_pending())
            return self._send(200, {"pending": n, **status})
        if self.path == "/pop":
            with lock:
                items = read_pending()
                write_pending([])
            return self._send(200, {"items": items, **status})
        self._send(404, {"error": "not found"})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit("HARK_API_KEY is missing in .env")
    threading.Thread(target=poll_loop, daemon=True).start()
    print(f"[bridge] listening on 127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

# --- /etc/systemd/system/hark-bridge.service ---
# [Unit]
# Description=Hark X bridge
# After=network-online.target
# [Service]
# WorkingDirectory=/root/banzaan-agent
# ExecStart=/usr/bin/python3 hark_bridge.py
# Restart=always
# [Install]
# WantedBy=multi-user.target
#
# --- /etc/systemd/system/hark-caddy.service ---
# [Unit]
# Description=HTTPS for Hark bridge
# After=network-online.target
# [Service]
# ExecStart=/usr/bin/caddy reverse-proxy --from 95-182-96-215.sslip.io --to localhost:8787
# Restart=always
# [Install]
# WantedBy=multi-user.target
#
# then: systemctl daemon-reload && systemctl enable --now hark-bridge hark-caddy

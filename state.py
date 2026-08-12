"""
state.py — SQLite-backed deduplication and rate-limit tracking.
"""
import sqlite3
import time
from datetime import datetime, timedelta
from config import DB_PATH


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS seen_tweets (
                tweet_id TEXT PRIMARY KEY,
                seen_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reply_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tweet_id        TEXT NOT NULL,
                author          TEXT,
                reply_text      TEXT,
                posted_at       TEXT,
                zernio_post_id  TEXT,
                status          TEXT
            );
        """)


def is_seen(tweet_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_tweets WHERE tweet_id = ?", (tweet_id,)
        ).fetchone()
        return row is not None


def mark_seen(tweet_id: str):
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_tweets (tweet_id, seen_at) VALUES (?, ?)",
            (tweet_id, datetime.utcnow().isoformat()),
        )


def log_reply(tweet_id: str, author: str, reply_text: str,
              zernio_post_id: str = None, status: str = "posted"):
    with _connect() as conn:
        conn.execute(
            """INSERT INTO reply_log
               (tweet_id, author, reply_text, posted_at, zernio_post_id, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tweet_id, author, reply_text,
             datetime.utcnow().isoformat(), zernio_post_id, status),
        )


def replies_in_last_hour() -> int:
    cutoff = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM reply_log WHERE posted_at > ? AND status = 'posted'",
            (cutoff,),
        ).fetchone()
        return row[0]


def prune_old_data(keep_days: int = 7):
    """Delete seen_tweets and reply_log entries older than keep_days to prevent DB bloat."""
    cutoff = (datetime.utcnow() - timedelta(days=keep_days)).isoformat()
    with _connect() as conn:
        r1 = conn.execute("DELETE FROM seen_tweets WHERE seen_at < ?", (cutoff,))
        r2 = conn.execute("DELETE FROM reply_log WHERE posted_at < ?", (cutoff,))
        pruned = r1.rowcount + r2.rowcount
    if pruned:
        # VACUUM must run outside a transaction
        conn = _connect()
        conn.execute("VACUUM")
        conn.close()
        print(f"[state] 🧹 Pruned {pruned} old entries and vacuumed DB.")

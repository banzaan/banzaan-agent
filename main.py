"""
main.py — Orchestrator loop for the reply-guy-bot.

Modes:
    python main.py              # runs the full loop indefinitely
    python main.py --once       # run exactly one poll cycle then exit
    python main.py --dry-run    # fetch + generate but DO NOT post
"""
import sys
import time
import random
import os
import shutil

import state
import monitor
import generator
import telegram_notifier
from config import (
    POLL_INTERVAL_SECONDS,
    MAX_REPLIES_PER_HOUR,
    MAX_REPLIES_PER_POLL,
    REPLY_DELAY_MIN,
    REPLY_DELAY_MAX,
    COOKIES_PATH,
)


def run_cycle(dry_run: bool = False) -> bool:
    """Returns False if the monitor API was unreachable, True otherwise."""
    print("\n━━━ Polling Twitter list ━━━")
    new_tweets = monitor.fetch_new_tweets(dry_run=dry_run)

    if new_tweets is None:
        print("[main] Monitor API unreachable this cycle.")
        return False

    if not new_tweets:
        print("[main] No new tweets this cycle.")
        return True

    # Ranking: if there are more new tweets than we can reply to, pick the best ones.
    if len(new_tweets) > MAX_REPLIES_PER_POLL:
        print(f"[main] Fetched {len(new_tweets)} tweets. Asking AI to rank top {MAX_REPLIES_PER_POLL} most interesting...")
        tweets_data = [{'id': getattr(t, 'tweet_id', t.tweet_id), 'author': getattr(t, 'author', t.author), 'text': getattr(t, 'text', t.text)} for t in new_tweets]
        best_ids = generator.select_best_tweets(tweets_data, limit=MAX_REPLIES_PER_POLL)
        new_tweets = [t for t in new_tweets if t.tweet_id in best_ids][:MAX_REPLIES_PER_POLL]
        print(f"[main] Selected {len(new_tweets)} top tweets for replies.")

    for tweet in new_tweets:
        # Hourly rate limit check
        count = state.replies_in_last_hour()
        if count >= MAX_REPLIES_PER_HOUR:
            print(f"[main] Rate limit reached ({count}/{MAX_REPLIES_PER_HOUR} replies/hr). Skipping remaining tweets.")
            break

        print(f"\n[main] Processing @{tweet.author}: {tweet.text[:80]}...")

        # Generate reply
        reply = generator.generate_reply(tweet.text, tweet.author)
        if not reply:
            print("[main] ⚠️  Generator returned empty — skipping.")
            state.log_reply(tweet.tweet_id, tweet.author, "", status="skipped_empty")
            continue

        print(f"[main] Generated reply ({len(reply)} chars):\n  → {reply}")

       # Send to Telegram for manual review instead of posting automatically
        tweet_id = getattr(tweet, 'tweet_id', tweet.tweet_id)
        author = getattr(tweet, 'author', tweet.author)

        success = telegram_notifier.send_reply_to_telegram(tweet_id, author, tweet.text, reply)
        status = "sent_to_telegram" if success else "failed"


        state.log_reply(tweet_id, author, reply, zernio_post_id=None, status=status)
        if not dry_run and len(new_tweets) > 1:
            delay = random.randint(REPLY_DELAY_MIN, REPLY_DELAY_MAX)
            print(f"[main] Sleeping {delay}s before next reply...")
            time.sleep(delay)

    return True


def main():
    dry_run = "--dry-run" in sys.argv
    run_once = "--once" in sys.argv

    state.init_db()
    state.prune_old_data(keep_days=7)

    # --- Initialize Persistent Cookies ---
    if COOKIES_PATH != "cookies.json" and not os.path.exists(COOKIES_PATH):
        if os.path.exists("cookies.json"):
            print(f"[main] 📦 Automatically copying initial cookies.json to volume path: {COOKIES_PATH}")
            shutil.copy("cookies.json", COOKIES_PATH)
        else:
            print(f"[main] ⚠️ Initial cookies.json not found. You will need to upload it to {COOKIES_PATH}.")

    print(f"[main] 🚀 reply-guy-bot started{'  (DRY RUN)' if dry_run else ''}")
    print(f"[main] Poll interval: {POLL_INTERVAL_SECONDS}s | Max {MAX_REPLIES_PER_POLL} replies/poll | Max {MAX_REPLIES_PER_HOUR} replies/hr")

    if run_once:
        run_cycle(dry_run=dry_run)
        print("[main] --once flag set. Exiting.")
        return

    consecutive_api_failures = 0
    while True:
        try:
            ok = run_cycle(dry_run=dry_run)
        except KeyboardInterrupt:
            print("\n[main] Stopped by user.")
            break
        except Exception as e:
            print(f"[main] ❌ Unexpected error: {e}")
            ok = True  # only monitor-API failures count toward the restart watchdog

        if ok:
            consecutive_api_failures = 0
        else:
            consecutive_api_failures += 1
            # Some hosts drop container networking under a long-running process.
            # Exiting non-zero lets a restart-on-failure policy give us a fresh
            # container with fresh networking.
            if consecutive_api_failures >= 5:
                print(f"[main] ❌ {consecutive_api_failures} consecutive API failures. Exiting so the host restarts with fresh networking.")
                sys.exit(1)

        print(f"[main] Sleeping {POLL_INTERVAL_SECONDS}s until next poll...")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

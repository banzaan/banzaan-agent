"""
monitor.py — Fetches new tweets from a Twitter list using Playwright with cookies.

Usage:
    python monitor.py             # normal mode
    python monitor.py --dry-run   # just print, no DB writes
"""
import sys
import json
import asyncio
from typing import List, Optional
from dataclasses import dataclass
from playwright.async_api import async_playwright

from config import LIST_ID, COOKIES_PATH
import state
import os
from dotenv import load_dotenv

load_dotenv()



env_auth_token = os.getenv("TWITTER_AUTH_TOKEN")
env_ct0 = os.getenv("TWITTER_CT0")

@dataclass
class Tweet:
    tweet_id: str
    author: str
    text: str

async def async_fetch_tweets(dry_run: bool = False) -> Optional[List[Tweet]]:
    if not LIST_ID:
        print("[monitor] ❌ Error: TWITTER_LIST_ID is not set in .env")
        return []

    # Load cookies from cookies.json
    # Load cookies from cookies.json
    cookies = []
    try:
        with open(COOKIES_PATH, 'r', encoding='utf-8') as f:
            raw_cookies = json.load(f)
            for c in raw_cookies:
                name = c["name"]
                value = c["value"]
                
                if name == "auth_token" and env_auth_token:
                    value = env_auth_token
                elif name == "ct0" and env_ct0:
                    value = env_ct0

                cookie = {
                    "name": name,
                    "value": value,
                    "domain": c.get("domain", ".x.com").lstrip('.'),
                    "path": c.get("path", "/")
                }
                cookies.append(cookie)
    except Exception as e:
        print(f"[monitor] ❌ Failed to read cookies.json: {e}")
        return []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Add cookies to Playwright session
        await context.add_cookies(cookies)
        page = await context.new_page()

        print(f"[monitor] Opening Twitter List: {LIST_ID} via Playwright...")
        try:
            await page.goto(f"https://x.com/i/lists/{LIST_ID}", wait_until="domcontentloaded", timeout=30000)
            await page.evaluate("window.scrollBy(0, 500)") 
            await page.wait_for_selector('article', timeout=60000)
            
            tweets = await page.eval_on_selector_all('article', '''elements => {
                return elements.map(el => {
                    
                    const isReply = el.innerText.includes('Replying to');
                    if (isReply) return null; 

                    const statusLink = el.querySelector('a[href*="/status/"]');
                    const id = statusLink ? statusLink.href.split('/').pop() : null;
                    const textEl = el.querySelector('[data-testid="tweetText"]');
                    const text = textEl ? textEl.innerText : null;
                    const userEl = el.querySelector('[data-testid="User-Name"]');
                    let author = "unknown";
                    if (userEl) {
                        const match = userEl.innerText.match(/@([a-zA-Z0-9_]+)/);
                        if (match) author = match[1];
                    }
                    return { id, text, author };
                }).filter(t => t !== null); 
            }''')
            
            await browser.close()
            
            new_tweets = []
            for item in tweets:
                if item['id'] and item['text']:
                    tweet_id = item['id']
                    text = item['text']
                    author = item['author']
                    
                    tweet = Tweet(tweet_id=tweet_id, author=author, text=text)
                    if dry_run:
                        print(f"  [dry-run] @{author} ({tweet_id}): {text[:80].replace(chr(10), ' ')}")
                        new_tweets.append(tweet)
                    elif not state.is_seen(tweet_id):
                        state.mark_seen(tweet_id)
                        new_tweets.append(tweet)
            
            print(f"[monitor] {len(new_tweets)} new tweet(s) to process")
            new_tweets.reverse()
            return new_tweets

        except Exception as e:
            print(f"[monitor] ❌ Playwright error: {e}")
            await browser.close()
            return None

def fetch_new_tweets(dry_run: bool = False) -> Optional[List[Tweet]]:
    return asyncio.run(async_fetch_tweets(dry_run=dry_run))

if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    state.init_db()
    results = fetch_new_tweets(dry_run=dry)
    if not results:
        print("[monitor] Nothing new.")
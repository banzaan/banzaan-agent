import os
import re
import google.generativeai as genai
from config import OPENAI_API_KEY, OPENAI_MODEL, BOT_HANDLE


genai.configure(api_key=OPENAI_API_KEY)
model_name = OPENAI_MODEL if OPENAI_MODEL else "gemini-1.5-flash"
model = genai.GenerativeModel(model_name)

from config import (
    OPENAI_API_KEY, 
    OPENAI_MODEL, 
    BOT_HANDLE, 
    SYSTEM_PROMPT_BASE,  
    REPLY_MOODS         
)
import random

def generate_reply(tweet_text: str, author: str) -> str:
    """
    Generates a reply to a tweet using Google Gemini with the strict rules defined in config.py.
    """

    mood = random.choice(REPLY_MOODS)
    

    prompt = SYSTEM_PROMPT_BASE.format(
        mood=mood,
        author=author,
        tweet_text=tweet_text
    )
    
    try:
        response = model.generate_content(prompt)
        reply = response.text.strip()


        if BOT_HANDLE:
            handle = "@" + BOT_HANDLE.lstrip("@").lower()
            if reply.lower().startswith(handle):
                reply = reply[len(handle):].lstrip(": ").strip()
        
        return reply
    except Exception as e:
        print(f"[generator] ❌ Gemini Error: {e}")
        return None


def select_best_tweets(tweets_data: list, limit: int = 3) -> list:
    """
    Selects the top most interesting tweets using Gemini.
    """
    if len(tweets_data) <= limit:
        return [t['id'] for t in tweets_data]

    prompt = (
        f"Evaluate the following {len(tweets_data)} tweets. Select the {limit} most interesting "
        "ones to reply to. Return ONLY a comma-separated list of the numerical indices (e.g. 0, 3, 4). No other text.\n\n"
    )

    for i, t in enumerate(tweets_data):
        prompt += f"[{i}] Author: @{t['author']}\nText: {t['text']}\n\n"

    try:
        response = model.generate_content(prompt)
        content = response.text.strip()
        
        indices = [int(n) for n in re.findall(r'\d+', content)]
        selected_ids = []
        for idx in indices:
            if 0 <= idx < len(tweets_data):
                selected_ids.append(tweets_data[idx]['id'])

        if not selected_ids:
            return [t['id'] for t in tweets_data[:limit]]

        return selected_ids[:limit]
    except Exception as e:
        print(f"[generator] Error selecting best tweets with Gemini: {e}")
        return [t['id'] for t in tweets_data[:limit]]
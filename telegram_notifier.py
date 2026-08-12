import os
import asyncio
from telegram import Bot
from dotenv import load_dotenv
from deep_translator import GoogleTranslator  

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def translate_to_farsi(text: str) -> str:
    
    try:
        translated = GoogleTranslator(source='auto', target='fa').translate(text)
        return translated
    except Exception as e:
        print(f"[telegram] ⚠️ Translation error: {e}")
        return 

def send_reply_to_telegram(tweet_id, author, tweet_text, reply_text):
    """
    Sends three separate messages to Telegram:
    1. Direct link to the original tweet.
    2. Raw reply text (for easy copying).
    3. Persian translation of the reply.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[telegram] ⚠️ Telegram token or chat ID is missing in environment variables.")
        return False

    tweet_url = f"https://x.com/{author}/status/{tweet_id}"
    
    msg_link = tweet_url
    msg_reply = reply_text.strip()
    
    if (msg_reply.startswith('"') and msg_reply.endswith('"')) or \
       (msg_reply.startswith("'") and msg_reply.endswith("'")):
        msg_reply = msg_reply[1:-1].strip()


    farsi_translation = translate_to_farsi(msg_reply)
    msg_translation = f"🇮🇷 ترجمه: {farsi_translation}"

    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        
        async def send_three_messages():
         
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg_link)
            await asyncio.sleep(0.5)
            
            
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg_reply)
            await asyncio.sleep(0.5)
            
           
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg_translation)

        asyncio.run(send_three_messages())
        print(f"[telegram] ✅ Sent tweet link, raw reply, and translation for tweet {tweet_id}.")
        return True
        
    except Exception as e:
        print(f"[telegram] ❌ Failed to send messages to Telegram: {e}")
        return False
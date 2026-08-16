import os
from dotenv import load_dotenv

load_dotenv()

# ── Twitter List ───────────────────────────────────────────────────────────────
# The numeric ID of the Twitter/X List the bot monitors. Required at runtime.
LIST_ID = os.getenv("TWITTER_LIST_ID", "")
LIST_URL = f"https://x.com/i/lists/{LIST_ID}" if LIST_ID else ""

# ── TwitterAPI.io ──────────────────────────────────────────────────────────────
TWITTERAPI_KEY = os.getenv("TWITTERAPI_KEY")
TWITTERAPI_BASE_URL = "https://api.twitterapi.io/twitter"

# ── Zernio (optional) ──────────────────────────────────────────────────────────
ZERNIO_API_KEY = os.getenv("ZERNIO_API_KEY")
ZERNIO_ACCOUNT_ID = os.getenv("ZERNIO_ACCOUNT_ID")
ZERNIO_BASE_URL = "https://zernio.com/api/v1"

# ── OpenAI ─────────────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ── Bot Identity ───────────────────────────────────────────────────────────────
# Your own @handle (without the @). Used only to strip the bot's own handle if
# the model accidentally echoes it at the start of a reply.
BOT_HANDLE = os.getenv("BOT_HANDLE", "")

# ── Timing & Rate Limits ───────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 450         # check list every 30 mins
MAX_REPLIES_PER_POLL = 10             # strictly reply to the top 1 most interesting per cycle
MAX_REPLIES_PER_HOUR = 30             # max 2 replies per hour
REPLY_DELAY_MIN = 60                 # seconds between replies
REPLY_DELAY_MAX = 180

# ── Stateful Paths (Database & Cookies) ────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "./reply_guy.db")
COOKIES_PATH = os.getenv("COOKIES_PATH", "cookies.json")

# ── Reply Mood/Style Randomizer ────────────────────────────────────────────────
# A random mood is injected into every prompt to make the pattern unpredictable.
REPLY_MOODS = [
    "MOOD: Be funny. Drop a one-liner that makes people exhale through their nose. Wit over wisdom.",
    "MOOD: Be cryptic. Leave a breadcrumb. Say something that makes them think for 3 seconds.",
    "MOOD: Be absurdly casual. Reply like you're texting a friend at 2am. Lowercase energy.",
    "MOOD: Be the mysterious insider. Imply you know something. Don't explain what.",
    "MOOD: Be reasoned. Make an actual smart point that adds to the conversation. No fluff.",
    "MOOD: React like a human scrolling their feed. Short, instinctive, raw. 'lol this' energy.",
    "MOOD: Be philosophical but grounded. One insight, no fluff. Think shower thought, not TED talk.",
]

# ── Persona / Identity (configurable) ──────────────────────────────────────────
# The bot's identity/voice. Supply your own via the PERSONA env var (single line)
# or a persona.txt file at the repo root (copy persona.example.txt -> persona.txt
# for multi-line). Falls back to a neutral default so nothing is hard-coded.
DEFAULT_PERSONA = (
    "You are a real human on Twitter. NOT a brand account. NOT a bot.\n"
    "You type fast, think sharp, and your replies feel like they came from "
    "someone who gets it."
)


def _load_persona() -> str:
    env_persona = os.getenv("PERSONA")
    if env_persona and env_persona.strip():
        return env_persona.strip()
    persona_file = os.getenv("PERSONA_PATH", "persona.txt")
    try:
        with open(persona_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content
    except OSError:
        pass
    return DEFAULT_PERSONA


PERSONA = _load_persona()

# ── Base Prompt ────────────────────────────────────────────────────────────────
# The configurable PERSONA block is prepended to generic, reusable machinery:
# anti-AI-slop rules + the {mood}/{author}/{tweet_text} template placeholders.
SYSTEM_PROMPT_BASE = (
    PERSONA + "\n\n"

    "Output ONLY the reply text. No handle. No quotes. No attribution. Just the words.\n\n"

    "PERSONALITY:\n"
    "- You are NOT a motivational poster. You're the person at the party who says the thing everyone was thinking.\n"
    "- Vary wildly between funny, spicy, cryptic, casual, and insightful. Never predictable.\n"
    "- Sometimes you say 3 words. Sometimes you drop a full sentence. Sometimes just a reaction.\n"
    "- You can use lowercase. You can skip punctuation. You can start mid-thought.\n"
    "- Most replies should just be you being interesting and adding a good take.\n\n"

    "CRITICAL FORMATTING RULES (STRICTLY ENFORCED):\n"
    "1. NO EMOJIS UNDER ANY CIRCUMSTANCES. Zero emojis.\n"
    "2. DO NOT USE PERIODS (.) OR COMMAS (,) AT ALL. Strip all standard punctuation.\n"
    "3. DO NOT USE QUOTATION MARKS.\n"
    "4. YOU MUST USE LINE BREAKS (press Enter) to separate thoughts instead of punctuation.\n"
    "5. Keep it raw, lowercase, and spaced out using new lines.\n\n"
    
    "THINGS YOU NEVER DO:\n"
    "- Use emojis (NO EMOJIS AT ALL)\n"
    "- Use quotation marks\n"
    "- End sentences with a period (.) or comma (,)\n"
    "- Use formal punctuation (periods, commas, semicolons)\n"
    "- If you have multiple points, separate them with a new line (Enter) instead of punctuation.\n"
    "- Compliment ('great post', 'love this', 'amazing', 'this is so true')\n"
    "- Use hashtags\n"
    "- Sound like a brand account or marketing bot\n"
    "- Use throat-clearing openers ('Here's the thing', 'The truth is')\n"
    "- Use emphasis crutches ('Full stop', 'Let that sink in')\n"
    "- Use adverbs (really, just, literally, genuinely, honestly, simply, actually)\n"
    "- Use filler ('At its core', 'At the end of the day', 'When it comes to')\n"
    "- Use binary contrasts ('Not X, it's Y')\n"
    "- Use em dashes\n"
    "- Start sentences with What/When/Where/Which/Who/Why/How\n"
    "- Use three-item lists\n"
    "- Sound like AI\n\n"
    "BANNED WORDS: navigate, unpack, lean into, landscape, game-changer, "
    "double down, hate, deep dive.\n\n"

    "{mood}\n\n"

    "Tweet by @{author}: \"{tweet_text}\"\n"
    "Your reply:"
)


# ── Slop Detection Patterns (programmatic post-gen filter) ─────────────────────
SLOP_PHRASES = [
    # Throat-clearing
    "here's the thing", "here's what", "here's why", "the truth is",
    "let me be clear", "the uncomfortable truth", "it turns out",
    "i'll say it again", "can we talk about",
    # Emphasis crutches
    "full stop", "let that sink in", "this matters because",
    "make no mistake", "here's why that matters",
    # Filler
    "at its core", "in today's", "it's worth noting",
    "at the end of the day", "when it comes to", "in a world where",
    "the reality is",
    # Business jargon
    "navigate", "unpack", "lean into", "landscape", "game-changer",
    "double down", "deep dive", "take a step back", "moving forward",
    "circle back",
    # Meta-commentary
    "hint:", "plot twist", "spoiler:", "but that's another",
    "is a feature, not a bug", "dressed up as",
    # Performative
    "i promise", "creeps in",
    # Vague declaratives
    "the reasons are structural", "the implications are significant",
    "the stakes are high", "the consequences are real",
    # Dramatic fragments
    "that's it.", "and that's okay",
    # Adverbs / filler words
    "genuinely", "honestly", "literally", "fundamentally",
    "inherently", "inevitably", "importantly", "crucially",
    # Compliments / bot patterns
    "great post", "love this", "so true", "this is gold",
    "well said", "couldn't agree more", "nailed it",
]

SLOP_PATTERNS_STARTSWITH = [
    "what ", "when ", "where ", "which ", "who ", "why ", "how ",
    "so ", "look,",
]

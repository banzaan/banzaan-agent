# reply-guy-bot

A headless Twitter/X reply bot that monitors a Twitter List, generates a
contextual, human-sounding reply with an LLM, runs it through a programmatic
anti-"AI slop" filter, and posts it from **your own account** by driving a real
browser with your exported session cookies.

It automates replies from your own account using your own browser session. Use
it responsibly and within X's terms of service. Nothing here is tied to any
particular brand or persona — the voice is fully configurable.

## How it works

```
                ┌──────────────┐   ┌───────────────────────┐   ┌──────────────────────┐   ┌──────────────┐
   Twitter List │  monitor.py  │ → │      generator.py     │ → │       poster.py      │ → │   X / Twitter│
   (TwitterAPI) │ poll timeline│   │ OpenAI + mood random  │   │ Playwright types the │   │  reply posted│
                │              │   │ + anti-slop filter    │   │ reply via cookies    │   │              │
                └──────┬───────┘   └───────────┬───────────┘   └──────────────────────┘   └──────────────┘
                       │                       │
                       └──── state.py (SQLite: dedupe seen tweets + hourly rate limits) ────┘
```

- **Monitor** (`monitor.py`): polls a Twitter List timeline via
  [TwitterAPI.io](https://twitterapi.io) (`/list/tweets_timeline`).
- **Generate** (`generator.py` + `config.py`): uses OpenAI (default
  `gpt-4o-mini`) to rank the most interesting tweets and write a reply. A mood
  randomizer injects 1 of 12 tones per attempt, and a two-layer anti-slop filter
  (prompt rules + a programmatic Python check for AI tells: throat-clearing
  openers, filler adverbs, em dashes, three-item lists, etc.) rejects and
  regenerates up to 3 times.
- **Post** (`poster.py`): drives a headless Playwright Chromium session, loads
  your exported `cookies.json`, physically types the reply into the inline
  composer, and clicks Reply. This is how it posts as you without the official
  write API.
- **State** (`state.py`): SQLite tracks seen tweets (dedupe) and enforces hourly
  rate limits; old rows are pruned automatically.

## Setup

Requires Python 3.9+.

```bash
git clone <your-repo-url>
cd reply-guy-bot
pip install -r requirements.txt
playwright install chromium
```

### 1. Environment

```bash
cp .env.example .env
# then edit .env with your keys and settings
```

### 2. Persona (optional)

```bash
cp persona.example.txt persona.txt
# edit persona.txt to define the bot's voice, or set PERSONA in .env,
# or leave it out entirely for the neutral default.
```

### 3. Cookies

Because X restricts write access via its API, the bot posts by typing in a real
browser session. You provide that session:

1. Log into **your own** X account in your everyday browser.
2. Export your cookies as JSON using a "Cookie Editor" style browser extension.
3. Save them as `cookies.json` at the repo root (see `cookies.example.json` for
   the expected shape).

`cookies.json` contains a live session — it is **gitignored** and must never be
committed or shared.

## Run

```bash
# Dry run: fetch + generate, but DO NOT post (safe to test)
python main.py --dry-run --once

# One real cycle then exit
python main.py --once

# Run the loop indefinitely
python main.py
```

Test components individually:

```bash
python monitor.py --dry-run     # show what the list returns
python generator.py             # interactively generate sample replies
python test_cookies.py          # verify your cookies.json loads in Playwright
```

## Environment variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | yes | — | OpenAI API key |
| `TWITTERAPI_KEY` | yes | — | TwitterAPI.io API key |
| `TWITTER_LIST_ID` | yes | — | Numeric ID of the List to monitor |
| `BOT_HANDLE` | recommended | — | Your @handle (no `@`); strips the bot's own handle if echoed |
| `OPENAI_MODEL` | no | `gpt-4o-mini` | OpenAI model to use |
| `PERSONA` | no | neutral default | Inline persona string |
| `PERSONA_PATH` | no | `persona.txt` | Path to a persona file |
| `DB_PATH` | no | `./reply_guy.db` | SQLite database path |
| `COOKIES_PATH` | no | `cookies.json` | Path to exported session cookies |
| `ZERNIO_API_KEY` | no | — | Optional, unused by core flow |
| `ZERNIO_ACCOUNT_ID` | no | — | Optional, unused by core flow |

Timing and rate limits (`POLL_INTERVAL_SECONDS`, `MAX_REPLIES_PER_POLL`,
`MAX_REPLIES_PER_HOUR`, `REPLY_DELAY_MIN/MAX`) are constants near the top of
`config.py`.

## Docker / Railway deploy

The included `Dockerfile` builds on the official Microsoft Playwright Python
image, so Chromium is preinstalled.

```bash
docker build -t reply-guy-bot .
docker run --rm reply-guy-bot
```

For 24/7 hosting (Railway, Render, a VPS, etc.):

1. With your own `cookies.json` present locally, build the image — `COPY . .`
   bakes your session into your **private** image. (`cookies.json` stays
   gitignored, so it never reaches the public repo.)
2. Set the environment variables (`OPENAI_API_KEY`, `TWITTERAPI_KEY`,
   `TWITTER_LIST_ID`, `BOT_HANDLE`, …) in your host's variables UI.
3. `railway.toml` configures a `DOCKERFILE` build with a restart-on-failure
   policy so the container recovers from transient networking drops.

For a persistent session across restarts, mount a volume and point
`COOKIES_PATH` at it; the bot copies your initial `cookies.json` onto the volume
on first boot and re-saves the refreshed session after each post.

## Checking logs

```bash
sqlite3 reply_guy.db "SELECT author, reply_text, posted_at FROM reply_log ORDER BY posted_at DESC LIMIT 10;"
```


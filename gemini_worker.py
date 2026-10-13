"""
gemini_worker.py: every 2 hours takes new posts from hark_bridge (/pop), filters junk with regex,
asks Gemini ONE time for all quotes + meme texts, builds memes with memegen.link and emails each
one to you on Telegram (Bot API over HTTPS). Hark is not used at all.

Put this file in /root/banzaan-agent (next to hark_bridge.py). Needs in .env:
  GEMINI_API_KEY=...            (aistudio.google.com)
  TELEGRAM_BOT_TOKEN=123456:ABC...   (from @BotFather)
  TELEGRAM_CHAT_ID=123456789          (your own chat id)
Optional: GEMINI_MODEL (default gemini-3.8-flash), RUN_EVERY_MIN (default 120), MAX_PER_RUN (default 10)
Test once:  python3 gemini_worker.py --once
"""
import json, os, random, re, sys, time, urllib.parse, urllib.request
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()
P = os.path.dirname(os.path.abspath(__file__))
HISTORY = os.path.join(P, "quotes_history.jsonl")
USED = os.path.join(P, "memes_used.txt")
MEMES = os.path.join(P, "memes")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
BRIDGE_KEY = os.getenv("HARK_API_KEY", "")
BRIDGE = f"http://127.0.0.1:{os.getenv('HARK_BRIDGE_PORT', '8787')}"
EVERY = int(os.getenv("RUN_EVERY_MIN", "120")) * 60
MAX_PER_RUN = int(os.getenv("MAX_PER_RUN", "10"))
FALLBACK_MODELS = [m.strip() for m in os.getenv("GEMINI_FALLBACKS", "gemini-2.5-flash,gemini-2.5-flash-lite").split(",") if m.strip()]

STYLE = "VOICE: a real human SI researcher on X, not a brand, not a bot. Simple English (top 500 words). This is a QUOTE post, not a reply: it must bring something the original post does not say.\nSTANDALONE TEST: if nobody saw the original post, the quote must still make sense and say something worth reading. A pure reaction (lol, wild, this is big, finally) fails.\nADD ONE NEW THING: the next step the author did not reach, a clear reason to disagree, a number or fact that sharpens the claim, what this changes for normal people or builders, or a concrete example. Use only facts you are sure of; never invent numbers.\nRULES: no emojis, no periods, no commas, no quotes, no em dashes, no hashtags. Lowercase except names (OpenAI, GPT, Claude, Google) and I. Use line breaks between thoughts.\nNEVER: compliments (great post, love this, so true), throat-clearing (here's the thing, the truth is), let that sink in, full stop, at the end of the day, when it comes to, not X it's Y, three-item lists, adverbs (really just literally honestly actually genuinely simply), starting with What/When/Where/Which/Who/Why/How/So, words navigate unpack landscape game-changer deep dive double down.\nVARY: each quote follows its own ANGLE and SHAPE below. Two quotes in one batch must never look alike in length or line layout.\n\nTERM: never write AI (or ai, A.I.) in the quote or the meme lines. Always write SI instead, uppercase (SI agents, SI race, open SI). Names like OpenAI and xAI stay as they are."
TEMPLATES = "drake: Drakeposting | 2 lines\ndb: Distracted Boyfriend | 3 lines\ngru: Gru's Plan | 4 lines\nfine: This is Fine | 2 lines\ncmm: Change My Mind | 1 lines\nds: Daily Struggle | 3 lines\ngb: Galaxy Brain | 4 lines\nstonks: Stonks | 2 lines\npanik-kalm-panik: Panik Kalm Panik | 3 lines\nnoidea: I Have No Idea What I'm Doing | 2 lines\nrollsafe: Roll Safe | 2 lines\nwonka: Condescending Wonka | 2 lines\nspiderman: Spider-Man Pointing at Spider-Man | 2 lines\npigeon: Is This a Pigeon? | 3 lines\nwoman-cat: Woman Yelling at a Cat | 2 lines\nhandshake: Epic Handshake | 3 lines\nmidwit: Midwit | 3 lines\nbuzz: X, X Everywhere | 2 lines\nboth: Why Not Both? | 2 lines\nchosen: You Were the Chosen One! | 2 lines\ndisastergirl: Disaster Girl | 2 lines\nharold: Hide the Pain Harold | 2 lines\nsuccess: Success Kid | 2 lines\nfry: Futurama Fry | 2 lines\ngandalf: Confused Gandalf | 2 lines\nmorpheus: Matrix Morpheus | 2 lines\ndoge: Doge | 2 lines\ncheems: Cheems | 2 lines\npooh: Tuxedo Winnie the Pooh | 2 lines\nexit: Left Exit 12 Off Ramp | 3 lines\ndrowning: Drowning High Five | 3 lines\nastronaut: Always Has Been | 4 lines\nright: Anakin and Padme Change the World For the Better | 5 lines\nreveal: Scooby Doo Reveal | 4 lines\nmordor: One Does Not Simply Walk into Mordor | 2 lines\nyodawg: Xzibit Yo Dawg | 2 lines\nafraid: Afraid to Ask Andy | 2 lines\nbad: You Should Feel Bad | 2 lines\nelmo: Elmo Choosing Cocaine | 5 lines\nkermit: But That's None of My Business | 2 lines\nmichael-scott: Michael Scott No God No | 2 lines\ndwight: Schrute Facts | 2 lines\nofficespace: That Would Be Great | 2 lines\ninteresting: The Most Interesting Man in the World | 2 lines\nleo: Leo Strutting | 2 lines\njw: Probably Not a Good Idea | 2 lines\nsame: They're The Same Picture | 3 lines\nbox: What's in the box!? | 2 lines\nolder: An Older Code Sir, But It Checks Out | 2 lines\nsadfrog: Feels Bad Man | 2 lines\nfacepalm: Facepalm | 2 lines\ngrave: Grant Gustin Next To Oliver Queen's Grave | 3 lines\nheadaches: Types of Headaches | 1 lines\nballoon: Running Away Balloon | 3 lines\nphilosoraptor: Philosoraptor | 2 lines\nslap: Will Smith Slapping Chris Rock | 2 lines\ntenguy: 10 Guy | 2 lines\nseagull: Inhaling Seagull | 2 lines\nkhaby-lame: Khaby Lame Shrug | 2 lines\nants: Do You Want Ants? | 2 lines\nscc: Sudden Clarity Clarence | 2 lines"
LINES = {"drake": 2, "db": 3, "gru": 4, "fine": 2, "cmm": 1, "ds": 3, "gb": 4, "stonks": 2, "panik-kalm-panik": 3, "noidea": 2, "rollsafe": 2, "wonka": 2, "spiderman": 2, "pigeon": 3, "woman-cat": 2, "handshake": 3, "midwit": 3, "buzz": 2, "both": 2, "chosen": 2, "disastergirl": 2, "harold": 2, "success": 2, "fry": 2, "gandalf": 2, "morpheus": 2, "doge": 2, "cheems": 2, "pooh": 2, "exit": 3, "drowning": 3, "astronaut": 4, "right": 5, "reveal": 4, "mordor": 2, "yodawg": 2, "afraid": 2, "bad": 2, "elmo": 5, "kermit": 2, "michael-scott": 2, "dwight": 2, "officespace": 2, "interesting": 2, "leo": 2, "jw": 2, "same": 3, "box": 2, "older": 2, "sadfrog": 2, "facepalm": 2, "grave": 3, "headaches": 1, "balloon": 3, "philosoraptor": 2, "slap": 2, "tenguy": 2, "seagull": 2, "khaby-lame": 2, "ants": 2, "scc": 2}
MOODS = [
    "extend: the post is right, add the next layer or consequence the author did not reach",
    "push back: disagree on a clear ground and say why",
    "sharpen: add a known fact, number or comparison that makes the claim more exact",
    "so what: say what this changes for builders, users or the SI race",
    "example: tie it to a concrete case, product or past event everyone knows",
    "spicy take: a bold but reasoned prediction that follows from the post",
]
SHAPES = [
    "one strong sentence, 12 to 20 words, one line",
    "two lines with a line break, no blank line, 20 to 35 words",
    "a short punchy first line then a blank line then one longer line, 25 to 40 words",
    "one long line, 25 to 35 words",
    "three short lines of different length, no blank lines, 20 to 35 words",
    "a claim line then a blank line then a sharp question line, 15 to 30 words",
]
FALLBACK = ["drake", "rollsafe", "stonks", "fine", "pooh", "success"]

# ---- filter (same rules as filter.py in Hark) ----
JUNK = re.compile(r"\b(promo|nft|mint(ing)?|airdrop|giveaway|points? (are )?live|whitelist|presale|token sale|"
                  r"gm|good (morning|night)|happy (monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
                  r"frens|fam|ct|socialfi|web3|onchain|quip|sleepagotchi|vangrid|teamily|lingoai|daolabs|heroes of valdir|try grok|#\w*mining|\$\d+k/mo|dm me|link in bio)\b", re.I)
BLOCK = re.compile(r"physical[\s_-]*(ai|si)\b|#?physicalai|termix|vangrid|streamoors?|dgx[\s_-]*spark|rtx[\s_-]*(pro[\s_-]*)?6000|axis[\s_-]*robotics|\baxis[\s_-]*(dataset|suite|robot\w*|v\d|network|data|tasks?)\b|\$axis\b|sleep+agotchi|\$chi\b|remix[\s_.-]*gg|"
                   r"\b(tge|100x|1000x|to the moon|moonshot|pump(ing)?|ape (in|into)|gem alert|next \d+x|bullish on \$|buy (the dip|now)|launchpad|token launch|staking rewards|listing on (binance|bybit|okx|mexc))\b", re.I)
TICKER = re.compile(r"\$[a-z][a-z0-9]{1,9}\b", re.I)
CRYPTO = re.compile(r"\b(crypto|token|coin|memecoin|altcoin|solana|degen|dex|airdrop|wallet|ca:|contract address|onchain|defi|bags|chart)\b", re.I)


def keep(p):
    t = re.sub(r"https?://\S+|@\w+", "", p.get("text") or "").strip()
    full = " ".join([p.get("text") or "", p.get("author") or "", p.get("url") or ""])
    if BLOCK.search(full) or (TICKER.search(full) and CRYPTO.search(full)):
        return False
    return len(t) >= 25 and not JUNK.search(t)


def log(*a):
    print(datetime.now().strftime("%m-%d %H:%M"), *a, flush=True)


def seen_urls():
    try:
        return {json.loads(l)["url"] for l in open(HISTORY, encoding="utf-8") if l.strip()}
    except FileNotFoundError:
        return set()


def pop():
    req = urllib.request.Request(BRIDGE + "/pop", headers={"X-API-Key": BRIDGE_KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("items", [])


def recent_memes():
    try:
        return open(USED, encoding="utf-8").read().splitlines()[-30:]
    except FileNotFoundError:
        return []


def ask_gemini(posts):
    shapes = random.sample(SHAPES, len(SHAPES)) * 3
    parts = [STYLE, ""]
    for i, p in enumerate(posts):
        parts.append(f"--- POST {i+1}\nurl: {p['url']}\nauthor: {p.get('author','')}\n"
                     f"ANGLE: {random.choice(MOODS)}\nSHAPE: {shapes[i]}\ntext: {(p.get('text') or '')[:600]}\n")
    parts.append("--- TEMPLATES (id: name | panels). MEME RULE: give lines as a list with exactly that many texts, one per panel, none empty\n" + TEMPLATES)
    parts.append("--- RECENT MEMES (do not reuse these templates)\n" + "\n".join(recent_memes()))
    parts.append("--- OUTPUT: a JSON array, one object per post you quote: "
                 '{"url": same url, "quote": text with real line breaks, "topic": 3 to 6 words, '
                 '"template": template id, "lines": [panel texts]}. Use a different template for every post. '
                 "Leave out a post only if it has nothing worth adding (pure promo, empty, not about SI).")
    body = {"contents": [{"parts": [{"text": "\n".join(parts)}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}}
    models = [MODEL] + [m for m in FALLBACK_MODELS if m != MODEL]
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY})
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    out = json.load(r)
                text = out["candidates"][0]["content"]["parts"][0]["text"]
                if model != MODEL:
                    log("used fallback model", model)
                return json.loads(text)
            except urllib.error.HTTPError as e:
                log("gemini error", model, e.code, e.read()[:200])
                if e.code == 429 or e.code == 404:
                    break  # quota or unknown model: go to next model
                if e.code not in (500, 503):
                    return []
            except Exception as e:
                log("gemini error", model, e)
            time.sleep(60 * (attempt + 1))
    return []


EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")
SI_RE = re.compile(r"\b(?:A\.I\.?|[Aa][Ii])\b")


def to_si(s):
    return SI_RE.sub("SI", s or "")


def clean(q):
    q = to_si(EMOJI.sub("", q or ""))
    for ch in [".", ",", '"', "\u201c", "\u201d", "\u2014", "\u2013", ";", "#"]:
        q = q.replace(ch, " " if ch in ("\u2014", "\u2013") else "")
    out = "\n".join(" ".join(l.split()) for l in q.split("\n")).strip()
    while "\n\n\n" in out:
        out = out.replace("\n\n\n", "\n\n")
    return out


def enc(s):
    s = (s or " ").strip() or " "
    for a, b in [("_", "__"), ("-", "--"), (" ", "_"), ("?", "~q"), ("/", "~s"),
                 ("#", "~h"), ("%", "~p"), ('"', "''"), ("\n", "~n")]:
        s = s.replace(a, b)
    return urllib.parse.quote(s, safe="_~'")


def fit(lines, n):
    lines = [l for l in lines if (l or "").strip()]
    if len(lines) > n:
        lines = lines[:n - 1] + [" ".join(lines[n - 1:])]
    return lines + [" "] * (n - len(lines))


def make_meme(template, lines, name):
    os.makedirs(MEMES, exist_ok=True)
    for t in [template] + [f for f in FALLBACK if f != template]:
        n = LINES.get(t, 2)
        if t != template and n != len([l for l in lines if (l or "").strip()]):
            continue
        url = f"https://api.memegen.link/images/{t}/" + "/".join(enc(l) for l in fit(lines, n)) + ".png"
        path = os.path.join(MEMES, f"{name}.png")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (banzaan-agent)"})
            with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
                f.write(r.read())
            if os.path.getsize(path) > 10_000:
                return path, t
        except Exception as e:
            log("meme failed", t, e)
    return None, None


def tg(method, fields, files=None):
    boundary = "----banzaan" + str(random.randint(10**8, 10**9))
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for k, path in (files or {}).items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{os.path.basename(path)}\"\r\n"
                 "Content-Type: image/png\r\n\r\n").encode() + open(path, "rb").read() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/{method}", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    r = json.loads(urllib.request.urlopen(req, timeout=60).read())
    if not r.get("ok"):
        raise RuntimeError(r)


def send(quote, url, meme):
    text = f"{quote}\n\n{url}"
    if meme:
        tg("sendPhoto", {"chat_id": TG_CHAT, "caption": text[:1024]}, {"photo": meme})
    else:
        tg("sendMessage", {"chat_id": TG_CHAT, "text": text})


def run_once():
    items = pop()
    seen = seen_urls()
    posts, dup = [], set()
    for p in items:
        if p["url"] in seen or p["url"] in dup:
            continue
        dup.add(p["url"])
        if keep(p):
            posts.append(p)
    posts = posts[-MAX_PER_RUN:] if MAX_PER_RUN > 0 else posts
    log(f"popped {len(items)}, after filter {len(posts)}")
    if not posts:
        return
    results = ask_gemini(posts)
    if not results:
        log("no quotes from Gemini; posts dropped this round")
    by_url = {p["url"]: p for p in posts}
    sent = 0
    for b in results if isinstance(results, list) else []:
        if b.get("url") not in by_url:
            continue
        quote = clean(b.get("quote"))
        lines = [to_si(l) for l in (b.get("lines") or [])]
        name = b["url"].rstrip("/").split("/")[-1]
        meme, t = make_meme(b.get("template", "drake"), lines, name)
        try:
            send(quote, b["url"], meme)
            sent += 1
            if t:
                with open(USED, "a", encoding="utf-8") as f:
                    f.write(f"{date.today()} | {t} | {b.get('topic', '')}\n")
        except Exception as e:
            log("telegram failed", b["url"], e)
            continue
        with open(HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps({"url": b["url"], "quote": quote, "topic": b.get("topic", ""),
                                "template": t, "at": datetime.now().isoformat(timespec="seconds")},
                               ensure_ascii=False) + "\n")
    log(f"sent {sent}/{len(posts)}")


if __name__ == "__main__":
    for k, v in [("GEMINI_API_KEY", GEMINI_KEY), ("TELEGRAM_BOT_TOKEN", TG_TOKEN),
                 ("TELEGRAM_CHAT_ID", TG_CHAT), ("HARK_API_KEY", BRIDGE_KEY)]:
        if not v:
            raise SystemExit(f"{k} is missing in .env")
    if "--once" in sys.argv:
        run_once()
        sys.exit()
    while True:
        try:
            run_once()
        except Exception as e:
            log("run error", e)
        time.sleep(EVERY)

"""
gemini_worker.py: every 2 hours takes new posts from hark_bridge (/pop), filters junk with regex,
asks Gemini ONE time for all quotes + meme texts, builds memes with memegen.link and emails each
one to you on Telegram (Bot API over HTTPS). Hark is not used at all.

Put this file in /root/banzaan-agent (next to hark_bridge.py). Needs in .env:
  GEMINI_API_KEY=...            (aistudio.google.com)
  TELEGRAM_BOT_TOKEN=123456:ABC...   (from @BotFather)
  TELEGRAM_CHAT_ID=123456789          (your own chat id)
Optional: GEMINI_MODEL (default gemini-3.8-flash), GEMINI_EMBED_MODEL, RUN_EVERY_MIN (default 120), MAX_PER_RUN (default 10), BATCH_SIZE, MIN_MEME_SCORE (default 5)
Needs meme_kb.json next to this file (built by build_kb.py). Meme flow: quote+joke idea -> top 6 templates by meaning (Gemini embeddings) -> 3 drafts -> judge picks best.
Test once:  python3 gemini_worker.py --once
"""
import hashlib, json, math, os, random, re, sys, time, urllib.error, urllib.parse, urllib.request
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
BATCH = int(os.getenv("BATCH_SIZE", "3"))  # posts per Gemini call (smaller = better quotes)
RECENT_N = int(os.getenv("RECENT_MEMES", "30"))
EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
MIN_SCORE = float(os.getenv("MIN_MEME_SCORE", "5"))  # judge average 1-10; below this the quote goes without a meme
KB = json.load(open(os.path.join(P, "meme_kb.json"), encoding="utf-8"))
KB_EMB = os.path.join(P, "meme_kb_emb.json")
FALLBACK_MODELS = [m.strip() for m in os.getenv("GEMINI_FALLBACKS", "gemini-2.5-flash,gemini-2.5-flash-lite").split(",") if m.strip()]

STYLE = "VOICE: a real human SI researcher on X, not a brand, not a bot. Simple English (top 500 words). This is a QUOTE post, not a reply: it must bring something the original post does not say.\nSTANDALONE TEST: if nobody saw the original post, the quote must still make sense and say something worth reading. A pure reaction (lol, wild, this is big, finally) fails.\nADD ONE NEW THING: the next step the author did not reach, a clear reason to disagree, a number or fact that sharpens the claim, what this changes for normal people or builders, or a concrete example. Use only facts you are sure of; never invent numbers.\nRULES: no emojis, no periods, no commas, no quotes, no em dashes, no hashtags. Lowercase except names (OpenAI, GPT, Claude, Google) and I. Use line breaks between thoughts.\nNEVER: compliments (great post, love this, so true), throat-clearing (here's the thing, the truth is), let that sink in, full stop, at the end of the day, when it comes to, not X it's Y, three-item lists, adverbs (really just literally honestly actually genuinely simply), starting with What/When/Where/Which/Who/Why/How/So, words navigate unpack landscape game-changer deep dive double down.\nVARY: each quote follows its own ANGLE and SHAPE below. Two quotes in one batch must never look alike in length or line layout.\n\nTERM: never write AI (or ai, A.I.) in the quote or the meme lines. Always write SI instead, uppercase (SI agents, SI race, open SI). Names like OpenAI and xAI stay as they are."
TEMPLATES = "drake: Drakeposting | 2 lines\ndb: Distracted Boyfriend | 3 lines\ngru: Gru's Plan | 4 lines\nfine: This is Fine | 2 lines\ncmm: Change My Mind | 1 lines\nds: Daily Struggle | 3 lines\ngb: Galaxy Brain | 4 lines\nstonks: Stonks | 2 lines\npanik-kalm-panik: Panik Kalm Panik | 3 lines\nnoidea: I Have No Idea What I'm Doing | 2 lines\nrollsafe: Roll Safe | 2 lines\nwonka: Condescending Wonka | 2 lines\nspiderman: Spider-Man Pointing at Spider-Man | 2 lines\npigeon: Is This a Pigeon? | 3 lines\nwoman-cat: Woman Yelling at a Cat | 2 lines\nhandshake: Epic Handshake | 3 lines\nmidwit: Midwit | 3 lines\nbuzz: X, X Everywhere | 2 lines\nboth: Why Not Both? | 2 lines\nchosen: You Were the Chosen One! | 2 lines\ndisastergirl: Disaster Girl | 2 lines\nharold: Hide the Pain Harold | 2 lines\nsuccess: Success Kid | 2 lines\nfry: Futurama Fry | 2 lines\ngandalf: Confused Gandalf | 2 lines\nmorpheus: Matrix Morpheus | 2 lines\ndoge: Doge | 2 lines\ncheems: Cheems | 2 lines\npooh: Tuxedo Winnie the Pooh | 2 lines\nexit: Left Exit 12 Off Ramp | 3 lines\ndrowning: Drowning High Five | 3 lines\nastronaut: Always Has Been | 4 lines\nright: Anakin and Padme Change the World For the Better | 5 lines\nreveal: Scooby Doo Reveal | 4 lines\nmordor: One Does Not Simply Walk into Mordor | 2 lines\nyodawg: Xzibit Yo Dawg | 2 lines\nafraid: Afraid to Ask Andy | 2 lines\nbad: You Should Feel Bad | 2 lines\nelmo: Elmo Choosing Cocaine | 5 lines\nkermit: But That's None of My Business | 2 lines\nmichael-scott: Michael Scott No God No | 2 lines\ndwight: Schrute Facts | 2 lines\nofficespace: That Would Be Great | 2 lines\ninteresting: The Most Interesting Man in the World | 2 lines\nleo: Leo Strutting | 2 lines\njw: Probably Not a Good Idea | 2 lines\nsame: They're The Same Picture | 3 lines\nbox: What's in the box!? | 2 lines\nolder: An Older Code Sir, But It Checks Out | 2 lines\nsadfrog: Feels Bad Man | 2 lines\nfacepalm: Facepalm | 2 lines\ngrave: Grant Gustin Next To Oliver Queen's Grave | 3 lines\nheadaches: Types of Headaches | 1 lines\nballoon: Running Away Balloon | 3 lines\nphilosoraptor: Philosoraptor | 2 lines\nslap: Will Smith Slapping Chris Rock | 2 lines\ntenguy: 10 Guy | 2 lines\nseagull: Inhaling Seagull | 2 lines\nkhaby-lame: Khaby Lame Shrug | 2 lines\nants: Do You Want Ants? | 2 lines\nscc: Sudden Clarity Clarence | 2 lines"
LINES = {c["id"]: len(c["example"]) for c in KB}
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
NAME2ID = {}
for _l in TEMPLATES.splitlines():
    _id, _rest = _l.split(":", 1)
    NAME2ID[_rest.split("|")[0].strip().lower()] = _id.strip()


def norm_template(t):
    t = (t or "").strip().lower()
    if t in LINES:
        return t
    return NAME2ID.get(t) or NAME2ID.get(t.replace("-", " ")) or ""

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
    """template ids used in the last RECENT_N memes"""
    try:
        rows = open(USED, encoding="utf-8").read().splitlines()[-RECENT_N:]
    except FileNotFoundError:
        return []
    return [r.split("|")[1].strip() for r in rows if r.count("|") >= 2]


def recent_quotes(n=6):
    try:
        rows = open(HISTORY, encoding="utf-8").read().splitlines()[-n:]
        return [json.loads(r).get("quote", "") for r in rows if r.strip()]
    except FileNotFoundError:
        return []


def pick_template(wanted, n_lines, banned):
    """use Gemini's template if valid and fresh, else a random fresh one (same panel count preferred)"""
    t = norm_template(wanted)
    if t and t not in banned:
        return t
    free = [k for k in LINES if k not in banned] or list(LINES)
    same = [k for k in free if LINES[k] == n_lines]
    return random.choice(same or free)


# ---------- Gemini helpers ----------
def gemini_json(prompt, temperature=1.0):
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
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
                log("model", model)
                return json.loads(text)
            except urllib.error.HTTPError as e:
                log("gemini error", model, e.code, e.read()[:200])
                if e.code in (429, 404):
                    break
                if e.code not in (500, 503):
                    return None
            except Exception as e:
                log("gemini error", model, e)
            time.sleep(30 * (attempt + 1))
    return None


def embed(texts):
    """Gemini embeddings (free). returns list of vectors or None"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{EMBED_MODEL}:batchEmbedContents"
    reqs = [{"model": f"models/{EMBED_MODEL}", "content": {"parts": [{"text": t}]}} for t in texts]
    try:
        req = urllib.request.Request(url, data=json.dumps({"requests": reqs}).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY})
        with urllib.request.urlopen(req, timeout=60) as r:
            return [e["values"] for e in json.load(r)["embeddings"]]
    except Exception as e:
        log("embed error", e)
        return None


def card_text(c):
    return f"{c['name']}. dynamic: {c['dynamic']}. {c['meaning']}. use when {c['use_when']}"


def kb_vectors():
    sig = hashlib.md5((EMBED_MODEL + json.dumps(KB)).encode()).hexdigest()
    try:
        d = json.load(open(KB_EMB))
        if d.get("sig") == sig:
            return d["vecs"]
    except Exception:
        pass
    vecs = {}
    for i in range(0, len(KB), 50):
        part = KB[i:i + 50]
        v = embed([card_text(c) for c in part])
        if not v:
            return None
        vecs.update({c["id"]: x for c, x in zip(part, v)})
    json.dump({"sig": sig, "vecs": vecs}, open(KB_EMB, "w"))
    return vecs


def cos(a, b):
    num = sum(x * y for x, y in zip(a, b))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0


def candidates(idea, banned, k=6):
    """top-k fresh templates whose meaning fits the joke idea"""
    free = [c for c in KB if c["id"] not in banned] or KB
    vecs = kb_vectors()
    q = embed([idea]) if vecs else None
    if q:
        free.sort(key=lambda c: -cos(q[0], vecs.get(c["id"], [0])))
        top = free[:k]
    else:  # no embeddings: let the model see every fresh card (short)
        top = free
    return top


# ---------- stage 1: quote + joke idea ----------
def ask_quotes(posts):
    shapes = random.sample(SHAPES, len(SHAPES)) * 3
    parts = [STYLE, ""]
    for i, p in enumerate(posts):
        parts.append(f"--- POST {i+1}\nurl: {p['url']}\nauthor: {p.get('author','')}\n"
                     f"ANGLE: {random.choice(MOODS)}\nSHAPE: {shapes[i]}\ntext: {(p.get('text') or '')[:600]}\n")
    rq = [q for q in recent_quotes() if q]
    if rq:
        parts.append("--- YOUR LAST QUOTES (do not repeat their openings, words or layout)\n" + "\n---\n".join(rq))
    parts.append(
        "--- ALSO, for each post find the MEME IDEA, like a meme page admin would:\n"
        "core: the one point of the post+quote in under 15 words\n"
        "dynamic: the comic structure hiding in it, one of: preference, temptation, plan backfires, denial in chaos, bold claim, "
        "hard choice, escalating ideas, naive win, twist, incompetence, bad clever logic, sarcasm, same thing, misidentification, "
        "argument, common ground, bell curve, flood, betrayal, hidden pain, small win, suspicion, confusion, reveal, recursion, "
        "fancy rename, unmasking, hard task, warning, consequences, epiphany, obvious solution, correction, blocked goal\n"
        "joke: one sentence saying what is funny or ironic about it for SI people (the gap between hype and reality, who wins, who suffers)\n"
        "--- OUTPUT: a JSON array, one object per post you quote: "
        '{"url": same url, "quote": text with real line breaks, "topic": 3 to 6 words, "core": "...", "dynamic": "...", "joke": "..."}. '
        "Leave out a post only if it has nothing worth adding (pure promo, empty, not about SI).")
    r = gemini_json("\n".join(parts), 1.0)
    return r if isinstance(r, list) else []


# ---------- stage 2: write meme drafts on the best fitting templates ----------
def card_full(c):
    roles = c["roles"]
    ex = " | ".join(c["example"])
    return (f"id: {c['id']} | {c['name']} | panels: {len(c['example'])}\n  meaning: {c['meaning']}\n"
            f"  use when: {c['use_when']}\n  panel roles: {roles}\n  example: {ex}")


def ask_meme(post, b, cards):
    prompt = (
        "You make memes for an SI research account on X. Readers are devs and SI researchers. "
        "A good meme maps the post's idea onto the template's KNOWN meaning, so the template does half the joke. "
        "Each panel text must play the role that panel has in the template. Short: max 8 words a panel, often 2 to 5. "
        "Concrete nouns (model names, GPUs, evals, prod, the bill) beat abstract words. No emojis. "
        "Never write AI, write SI (OpenAI and xAI stay).\n\n"
        f"POST by {post.get('author','')}: {(post.get('text') or '')[:600]}\n"
        f"OUR QUOTE: {b.get('quote','')}\nCORE: {b.get('core','')}\nDYNAMIC: {b.get('dynamic','')}\nJOKE: {b.get('joke','')}\n\n"
        "TEMPLATES you may use:\n" + "\n".join(card_full(c) for c in cards) + "\n\n"
        "Write 3 different drafts on 3 different templates (only ids above). The lines array must have EXACTLY as many items as panels, "
        "in the same order as the panel roles, because line N is printed on block N of the image. Use an empty string for a block that should stay empty. "
        'OUTPUT JSON: {"drafts": [{"template": id, "lines": [panel texts], "why": "why the template meaning fits"}]}')
    r = gemini_json(prompt, 1.1)
    drafts = (r or {}).get("drafts") if isinstance(r, dict) else None
    ok = []
    for d in drafts or []:
        t = norm_template(d.get("template"))
        lines = [to_si(str(x or "")).strip() for x in (d.get("lines") or [])]
        # each line belongs to one block on the image: wrong count means text lands in the wrong block, so drop it
        if t not in {c["id"] for c in cards} or len(lines) != LINES[t] or not any(lines):
            log("draft dropped", t, f"{len(lines)} lines for {LINES.get(t)} blocks")
            continue
        ok.append({"template": t, "lines": lines, "why": d.get("why", "")})
    return ok


# ---------- stage 3: judge ----------
def judge(post, b, drafts):
    """returns drafts sorted best first and the best score"""
    if len(drafts) < 2:
        return drafts, (6 if drafts else 0)
    cards = {c["id"]: c for c in KB}
    listing = "\n".join(f"{i+1}. {d['template']} ({cards[d['template']]['meaning']}; roles: {cards[d['template']]['roles']}): "
                        + " | ".join(d["lines"]) for i, d in enumerate(drafts))
    prompt = ("You are a strict meme page editor for SI devs. Score each meme draft 1 to 10 on: "
              "fit (does the template's known meaning match the idea, and does each line match its panel role), "
              "funny (would an SI dev laugh or nod), clear (gets it in 2 seconds without the post). "
              f"POST: {(post.get('text') or '')[:500]}\nJOKE: {b.get('joke','')}\n\nDRAFTS:\n{listing}\n\n"
              'OUTPUT JSON: {"scores": [{"n": number, "fit": x, "funny": x, "clear": x}], "best": number}')
    r = gemini_json(prompt, 0.2)
    try:
        sc = {int(x["n"]): (x["fit"] + x["funny"] + x["clear"]) / 3 for x in r["scores"]}
        order = sorted(range(1, len(drafts) + 1), key=lambda n: -sc.get(n, 0))
        best = int(r.get("best") or order[0])
        if best in order:
            order.remove(best)
            order.insert(0, best)
        return [drafts[n - 1] for n in order], sc.get(best, 5)
    except Exception:
        return drafts, 6


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


def make_meme(ranked, name):
    """build the best draft; if memegen fails, try the next draft with its own lines (never put lines on another template)"""
    os.makedirs(MEMES, exist_ok=True)
    path = os.path.join(MEMES, f"{name}.png")
    for d in ranked[:3]:
        t, lines = d["template"], d["lines"]
        if len(lines) != LINES.get(t):
            continue
        url = f"https://api.memegen.link/images/{t}/" + "/".join(enc(l) for l in lines) + ".png"
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (banzaan-agent)"})
                with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
                    f.write(r.read())
                if os.path.getsize(path) > 10_000:
                    return path, d
            except Exception as e:
                log("meme failed", t, attempt, e)
                time.sleep(3)
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
    by_url = {p["url"]: p for p in posts}
    results = []
    for i in range(0, len(posts), max(1, BATCH)):
        results += ask_quotes(posts[i:i + BATCH])
    if not results:
        log("no quotes from Gemini; posts dropped this round")
    banned = set(recent_memes())
    sent = 0
    for b in results:
        if not isinstance(b, dict) or b.get("url") not in by_url:
            continue
        post = by_url[b["url"]]
        quote = clean(b.get("quote"))
        name = b["url"].rstrip("/").split("/")[-1]
        idea = f"{b.get('dynamic','')}. {b.get('core','')}. {b.get('joke','')}"
        cards = candidates(idea, banned)
        drafts = ask_meme(post, b, cards)
        ranked, score = judge(post, b, drafts)
        meme, t, best = None, None, None
        if ranked and score >= MIN_SCORE:
            meme, best = make_meme(ranked, name)
            t = best["template"] if best else None
            log("meme", t, f"score {score:.1f}", "|", " / ".join(best["lines"]) if best else "build failed")
        else:
            log("no meme good enough", f"score {score:.1f}")
        if t:
            banned.add(t)
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
                                "template": t, "lines": best["lines"] if (best and t) else None,
                                "joke": b.get("joke", ""), "score": round(score, 1),
                                "at": datetime.now().isoformat(timespec="seconds")},
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

import os
import re
import sys
import math
import random
import json
import hashlib
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import requests

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "artifacts"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
INDEX_PATH = Path(__file__).resolve().parent.parent / "index.html"
STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"

CYCLE_DAYS = 14
EPOCH = date(2026, 1, 1)
MONTHLY_BUDGET_USD = 5.0

FORAGE_LOG = Path(__file__).resolve().parent.parent / "forage.log"
COST_LOG = Path(__file__).resolve().parent.parent / "cost.log"
API_FILE = Path(__file__).resolve().parent.parent / "API.txt"
API_FREE_FILE = Path(__file__).resolve().parent.parent / "DGAPIFREE.txt"

WIKIPEDIA_API = "https://en.wikipedia.org/api/rest_v1/page/random/summary"

BACKENDS = []


# ── Budget & logging ──────────────────────────────────────────────

TOTAL_COST = [0.0]


def log_forage(source, status, detail=""):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {source}: {status}"
    if detail:
        entry += f" — {detail}"
    with open(FORAGE_LOG, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


def log_cost(cents, detail):
    TOTAL_COST[0] += cents
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with open(COST_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] ${cents:.5f} ({detail})\n")


def check_budget():
    if not COST_LOG.exists():
        return True
    lines = COST_LOG.read_text("utf-8").strip().split("\n")
    total_month = 0.0
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    for line in lines:
        m = re.search(r'\$(\d+\.\d+)', line)
        if not m:
            continue
        ts_match = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]', line)
        if ts_match:
            ts = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
        total_month += float(m.group(1))
    if total_month >= MONTHLY_BUDGET_USD:
        print(f"  [budget] ${total_month:.3f} >= ${MONTHLY_BUDGET_USD} — stopping")
        return False
    print(f"  [budget] ${total_month:.3f}/{MONTHLY_BUDGET_USD}")
    return True


# ── Temperature cycle ──────────────────────────────────────────────

def get_cycle_temp():
    return round(random.uniform(0.7, 2.0), 2)


# ── State ──────────────────────────────────────────────────────────

def read_state():
    if not STATE_PATH.exists():
        return {"cycle": 0, "last_title": "", "archive_count": 0}
    try:
        return json.loads(STATE_PATH.read_text("utf-8"))
    except (json.JSONDecodeError, KeyError):
        return {"cycle": 0, "last_title": "", "archive_count": 0}


def write_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


import xml.etree.ElementTree as ET

RSS_FEEDS = [
    "http://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.npr.org/1001/rss.xml",
]


def fetch_news():
    feed_url = random.choice(RSS_FEEDS)
    try:
        resp = requests.get(feed_url, timeout=15, headers={"User-Agent": "Amalgamma/2.0"})
        if resp.status_code != 200:
            log_forage("rss", f"HTTP {resp.status_code}", feed_url[:40])
            return None
        root = ET.fromstring(resp.content)
        items = root.findall(".//item")
        if not items:
            log_forage("rss", "no items")
            return None
        item = random.choice(items)
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        if description:
            description = re.sub(r"<[^>]+>", "", description)
            description = re.sub(r"\s+", " ", description)
        source = feed_url.split("//")[1].split("/")[0]
        log_forage("rss", "fetched", f"{source}: {title[:50]}")
        return {
            "title": title,
            "extract": description if len(description) > 50 else title,
            "description": source,
            "url": item.findtext("link", "")
        }
    except Exception as e:
        log_forage("rss", "fail", str(e)[:60])
    return None


# ── Wikipedia source ───────────────────────────────────────────────

def fetch_wikipedia():
    headers = {"User-Agent": "Amalgamma/2.0 (art-bot; https://github.com/look85-ops/amalgamma)"}
    try:
        resp = requests.get(WIKIPEDIA_API, timeout=15, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            title = data.get("title", "")
            extract = data.get("extract", "")
            description = data.get("description", "")
            url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
            log_forage("wikipedia", "fetched", title[:50])
            return {"title": title, "extract": extract, "description": description, "url": url}
        log_forage("wikipedia", f"HTTP {resp.status_code}")
    except Exception as e:
        log_forage("wikipedia", "fail", str(e)[:60])
    return None


# ── Backend registration ──────────────────────────────────────────

def register_backend(name, key, url, make_payload, parse_response,
                      models=None, paid=False, cost_per_1m_input=0, cost_per_1m_output=0,
                      needs_auth_header=True):
    if key:
        BACKENDS.append({
            "name": name, "key": key, "url": url,
            "make_payload": make_payload, "parse_response": parse_response,
            "models": models or [None], "paid": paid,
            "cost_in": cost_per_1m_input, "cost_out": cost_per_1m_output,
            "needs_auth_header": needs_auth_header,
        })
        tag = "paid" if paid else "free"
        log_forage(name, f"{tag} key loaded")
    else:
        log_forage(name, "no key")


PROXY_URL = os.environ.get("BOTHUB_URL", "https://openai.bothub.chat/v1")


def read_api_txt():
    raw = ""
    if API_FILE.exists():
        raw = API_FILE.read_text("utf-8")
    elif os.environ.get("EITHER_API_KEY", ""):
        raw = os.environ["EITHER_API_KEY"]
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        model, key = line.split(":", 1)
        if not model or not key:
            continue
        def payload_fn(m):
            return {
                "model": m,
                "messages": [{"role": "user", "content": "__PROMPT__"}],
                "temperature": get_cycle_temp(),
                "max_tokens": 800,
                "top_p": 0.95,
            }
        def parse_fn(data):
            usage = data.get("usage", {})
            in_tok = usage.get("prompt_tokens", 0)
            out_tok = usage.get("completion_tokens", 0)
            return data.get("choices", [{}])[0].get("message", {}).get("content", ""), in_tok, out_tok
        register_backend(f"proxy-{model}", key,
                         f"{PROXY_URL}/chat/completions",
                         payload_fn, parse_fn, models=[model],
                         paid=True, cost_per_1m_input=0.50, cost_per_1m_output=2.00)


def forager_openrouter():
    def payload_fn(model):
        return {
            "model": model,
            "messages": [{"role": "user", "content": "__PROMPT__"}],
            "temperature": get_cycle_temp(),
            "max_tokens": 800,
            "top_p": 0.95,
        }
    def parse_fn(data):
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        return (data.get("choices", [{}])[0].get("message", {}).get("content", "")
                or data.get("choices", [{}])[0].get("message", {}).get("reasoning", "")), 0, 0
    key = os.environ.get("OPENROUTER_API_KEY", "")
    register_backend("openrouter", key,
                     "https://openrouter.ai/api/v1/chat/completions",
                     payload_fn, parse_fn, [
                         "qwen/qwen3-coder:free",
                         "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
                     ])


def forager_gemini():
    def payload_fn(model):
        return {
            "contents": [{"parts": [{"text": "__PROMPT__"}]}],
            "generationConfig": {
                "temperature": get_cycle_temp(),
                "maxOutputTokens": 800,
                "topP": 0.95,
            },
        }
    def parse_fn(data):
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", ""), 0, 0
        raise RuntimeError("empty response")
    key = os.environ.get("GEMINI_API_KEY", "")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    if key:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        register_backend("gemini", key, url, payload_fn, parse_fn, needs_auth_header=False)


def read_free_api():
    raw = ""
    if API_FREE_FILE.exists():
        raw = API_FREE_FILE.read_text("utf-8")
    elif os.environ.get("FREE_API_KEYS", ""):
        raw = os.environ["FREE_API_KEYS"]
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("sk-"):
            continue
        def payload_fn(model):
            return {
                "model": model or "deepseek-chat",
                "messages": [{"role": "user", "content": "__PROMPT__"}],
                "temperature": get_cycle_temp(),
                "max_tokens": 800,
                "top_p": 0.95,
            }
        def parse_fn(data):
            usage = data.get("usage", {})
            in_tok = usage.get("prompt_tokens", 0)
            out_tok = usage.get("completion_tokens", 0)
            return data.get("choices", [{}])[0].get("message", {}).get("content", ""), in_tok, out_tok
        key = line.strip()
        backend = {
            "name": f"deepseek-free-{key[-8:]}",
            "key": key, "url": "https://api.deepseek.com/v1/chat/completions",
            "make_payload": payload_fn, "parse_response": parse_fn,
            "models": ["deepseek-chat"], "paid": False,
            "cost_in": 0, "cost_out": 0,
            "needs_auth_header": True,
        }
        BACKENDS.insert(0, backend)
        log_forage(f"deepseek-free-{key[-8:]}", "free key loaded")


read_free_api()
read_api_txt()
forager_openrouter()
forager_gemini()
BACKENDS.sort(key=lambda b: (not b["paid"], b["name"]))


# ── LLM call ────────────────────────────────────────────────────────

def call_llm(prompt):
    for backend in BACKENDS:
        if backend is None:
            continue
        name = backend["name"]
        is_paid = backend["paid"]
        print(f"  [trying {name}]", flush=True)
        headers = {}
        if backend["needs_auth_header"]:
            headers["Authorization"] = f"Bearer {backend['key']}"
        for model in backend["models"]:
            payload = backend["make_payload"](model)
            for msg in payload.get("messages", []):
                if isinstance(msg.get("content"), str):
                    msg["content"] = msg["content"].replace("__PROMPT__", prompt)
            try:
                resp = requests.post(backend["url"], headers=headers, json=payload, timeout=180)
                if resp.status_code >= 400:
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:100]}")
                data = resp.json()
                if "error" in data:
                    raise RuntimeError(data["error"].get("message", str(data["error"])))
                result = backend["parse_response"](data)
                if isinstance(result, tuple):
                    content, in_tok, out_tok = result
                else:
                    content, in_tok, out_tok = result, 0, 0
                if content and len(content) > 10:
                    if is_paid and (in_tok or out_tok) and backend["cost_in"] > 0:
                        cost = (in_tok * backend["cost_in"] + out_tok * backend["cost_out"]) / 1_000_000
                        log_cost(cost, f"{name}/{model}: {in_tok}↑ {out_tok}↓")
                    log_forage(name, "success", f"model={model}")
                    return content
                log_forage(name, "short/no content", f"model={model}")
            except Exception as e:
                log_forage(name, "failed", f"model={model or 'default'}: {str(e)[:60]}")
                continue
    print("  [all backends exhausted]")
    sys.exit(1)


# ── Prompt ──────────────────────────────────────────────────────────

def build_prompt(article):
    title = article["title"]
    extract = article["extract"]
    temp = get_cycle_temp()

    return (
        f"You are an artist working in the tradition of Rothko, Soulages, "
        f"Twombly, Agnes Martin, Malevich, Kandinsky. Your language is "
        f"non-figurative: rhythm, silence, scale, materiality. Not beauty — "
        f"presence. Not decoration — experience. The kind of work where "
        f"the heart stops for a moment.\n\n"
        f"Your medium is fullscreen HTML/CSS: bands that breathe, blocks "
        f"that weigh, pulses that beat, particles that drift, blobs that "
        f"bleed. Code as paint. The browser as canvas.\n\n"
        f"Below is today's headline. Do not illustrate it. Feel its weight, "
        f"its rhythm, its silence. Respond with a composition that holds "
        f"space — emptiness is not absence, it is structure. Fewer elements, "
        f"deeper presence.\n\n"
        f"TITLE: {title}\n"
        f"TEXT: {extract}\n\n"
        f"Respond with JSON only, no markdown:\n"
        f'{{"bg":"hex — deep, absorbing, not decorative",\n'
        f' "palette":["hex","hex"] — 2-3 colours max, earthy or deep, no candy,\n'
        f' "mood":"one word — the weight of this news",\n'
        f' "intensity":"low|medium|high — restraint is a choice",\n'
        f' "gesture":"one sentence — the single artistic move on screen",\n'
        f' "structure":"30-50 words — one or two forms, their scale, the space between them",\n'
        f' "motion":"10-15 words — rhythm, not animation; breath, not spectacle"}}'
    )


# ── Parametric parser ──────────────────────────────────────────────

def _mod(count_lo, count_hi, size_lo, size_hi, speed_lo, speed_hi, intensity):
    # intensity = restraint, not chaos. "low" is intentional minimalism.
    # Fewer elements, bigger scale, slower rhythm.
    cm, sm, spm = {"high": (1.2, 1.2, 1.3), "medium": (1.0, 1.0, 1.0), "low": (0.4, 1.5, 0.6)}.get(intensity, (1.0, 1.0, 1.0))
    return (
        max(1, int(random.randint(count_lo, count_hi) * cm)),
        round(random.uniform(size_lo, size_hi) * sm, 1),
        round(random.uniform(speed_lo, speed_hi) * spm, 1),
    )


def _parse_primitives(structure, gesture, mood, intensity):
    s = (structure + " " + gesture + " " + mood).lower()

    has = lambda words: any(w in s for w in words)

    primitives = []

    if has(["particle", "dot", "speck", "dust", "grain", "point", "scatter", "spread",
            "disperse", "constellation", "star", "swarm", "crowd", "many",
            "cluster", "galaxy", "atom", "pixel", "noise", "static"]):
        c, sz, sp = _mod(8, 60, 1.0, 10.0, 0.15, 0.8, intensity)
        primitives.append(("particles", c, sz, sp))

    if has(["band", "horizon", "stripe", "layer", "drift", "sky", "ocean", "weather",
            "cloud", "fog", "mist", "haze", "dawn", "dusk", "sunset", "sunrise",
            "vast", "endless", "float", "hover", "suspension", "atmospher", "airy",
            "field", "plane", "expanse", "horizon", "void", "empty", "silence"]):
        c, sz, sp = _mod(2, 10, 0.5, 8.0, 0.10, 0.6, intensity)
        primitives.append(("bands", c, sz, sp))

    if has(["block", "grid", "build", "city", "architect", "square", "rect",
            "geometry", "geometric", "sharp", "shard", "fracture", "jagged",
            "edge", "angular", "line", "parallel", "converge", "intersect",
            "slab", "plate", "facet", "prism", "beam", "pillar", "column",
            "tower", "wall", "frame", "scaffold", "crush", "collide", "rigid",
            "monolith", "weight", "heavy", "massive", "solid"]):
        c, sz, sp = _mod(3, 40, 3, 25, 0.15, 0.8, intensity)
        primitives.append(("blocks", c, sz, sp))

    if has(["blob", "liquid", "fluid", "bleed", "water", "wash", "stain",
            "organic", "melt", "flow", "wave", "ripple", "ooze", "seep",
            "dissolve", "merge", "blur", "soft", "morph", "distort", "warp",
            "bend", "curve", "swoop", "drip", "pour", "stream", "flood",
            "pool", "depth", "deep"]):
        c, sz, sp = _mod(1, 8, 25, 90, 0.10, 0.5, intensity)
        primitives.append(("blobs", c, sz, sp))

    if has(["pulse", "breathe", "beat", "heart", "glow", "single", "alone",
            "centre", "center", "core", "flash", "flicker", "throb", "rhythm",
            "syncopat", "spike", "surge", "shaky", "trembl", "quiver", "vibrat",
            "oscillat", "strobe", "blink", "nervous", "glitch", "presence"]):
        c, sz, sp = _mod(1, 3, 25, 60, 0.3, 1.5, intensity)
        primitives.append(("pulses", c, sz, sp))

    if not primitives:
        return None

    # glass texture is always on — digital materiality, like paint weight
    glass = True

    random.shuffle(primitives)
    # minimalism: 1-2 forms, rarely 3
    n = min(len(primitives), random.choices([1, 2, 3], weights=[0.5, 0.35, 0.15], k=1)[0])

    return {
        "primitives": primitives[:n],
        "glass": glass,
        "names": [p[0] for p in primitives[:n]],
    }


# ── HTML generator ─────────────────────────────────────────────────

def _structure_weights(structure, mood, intensity):
    s = (structure + " " + mood).lower()
    weights = {
        "atmospheric": 1.0,
        "strokes": 1.0,
        "field": 1.0,
        "pulse": 1.0,
        "liquid": 1.0,
    }

    keyword_map = {
        "atmospheric": ["horizon", "band", "sky", "ocean", "drift", "weather",
                        "cloud", "fog", "mist", "haze", "dawn", "dusk", "wind",
                        "vast", "endless", "horizon", "sunset", "sunrise",
                        "atmospher", "airy", "breath", "float", "hover", "suspension"],
        "strokes": ["block", "grid", "build", "city", "architect",
                           "square", "rect", "geometry", "geometric", "sharp", "shard",
                           "fracture", "jagged", "edge", "angular", "line",
                           "parallel", "converge", "intersect", "structure",
                           "slab", "plate", "facet", "prism", "beam", "pillar",
                           "column", "tower", "wall", "frame", "scaffold",
                           "crush", "collide", "impact", "collision"],
        "field": ["particle", "field", "constellation", "dot", "scatter",
                  "star", "dust", "plankton", "swarm", "crowd", "many",
                  "countless", "spread", "disperse", "scattered", "cluster",
                  "galaxy", "atoms", "grains", "speck", "speckle",
                  "pointill", "pixel", "noise", "static", "grainy"],
        "pulse": ["pulse", "breathe", "beat", "heart", "glow", "single",
                  "alone", "centre", "center", "core", "flash", "flicker",
                  "throb", "rhythm", "syncopat", "spike", "surge",
                  "shaky", "trembl", "quiver", "vibrat", "oscillat",
                  "flicker", "strobe", "blink", "heartbeat", "nervous"],
        "liquid": ["liquid", "fluid", "bleed", "water", "wash", "stain",
                   "organic", "blob", "melt", "flow", "wave", "ripple",
                   "ooze", "seep", "dissolve", "merge", "blur", "soft",
                   "morph", "distort", "warp", "bend", "curve", "swoop",
                   "drip", "pour", "stream", "flood", "spill"],
    }

    for grammar, keywords in keyword_map.items():
        for kw in keywords:
            if kw in s:
                weights[grammar] += 1.5

    # intensity modulation
    if intensity == "high":
        for g in weights:
            weights[g] *= 1.3
    elif intensity == "low":
        for g in weights:
            weights[g] *= 0.7

    return weights


def generate_html(vision, article_title, article_url, cycle_num):
    bg = vision.get("bg", "#0a0a14")
    palette = vision.get("palette", ["#b7f562", "#8b6fc0", "#e8dcc8", "#2a2540"])
    intensity = vision.get("intensity", "medium")
    mood = vision.get("mood", "")
    structure = vision.get("structure", "")
    gesture = vision.get("gesture", "")

    print(f"  intensity: {intensity}")
    print(f"  gesture: {gesture[:80]}")
    print(f"  structure: {structure[:80]}")

    c1 = palette[0] if len(palette) > 0 else "#b7f562"
    c2 = palette[1] if len(palette) > 1 else "#8b6fc0"
    c3 = palette[2] if len(palette) > 2 else "#e8dcc8"
    c4 = palette[3] if len(palette) > 3 else "#2a2540"

    grammar_map = {
        "particles": ("field", lambda: (_field(palette, bg, intensity), _css_field(palette), _glass_layer(), _css_glass())),
        "bands": ("atmospheric", lambda: (_atmospheric(palette, bg, intensity), _css_atmospheric(palette), _glass_layer(), _css_glass())),
        "blocks": ("strokes", lambda: (_strokes(palette, bg, intensity), _css_strokes(palette, bg), _glass_layer(), _css_glass())),
        "blobs": ("liquid", lambda: (_liquid(palette, bg, intensity), _css_liquid(palette), "", "")),
        "pulses": ("pulse", lambda: (_pulse(palette, bg, intensity), _css_pulse(palette), "", "")),
    }

    params = _parse_primitives(structure, gesture, mood, intensity)

    if params and len(params["primitives"]) >= 2:
        selected_names = params["names"]
        selected_fns = [grammar_map[ptype][1] for ptype, _, _, _ in params["primitives"]]
        use_glass = params["glass"]
        print(f"  primitives: {' + '.join(selected_names)}")
    else:
        # fallback — weighted grammar selection
        all_grammars = list(grammar_map.values())
        weights = _structure_weights(structure, mood, intensity)
        grammar_names = [g[0] for g in all_grammars]
        w = [weights[name] for name in grammar_names]
        n = random.randint(2, 4)
        selected_names = []
        selected_fns = []
        remaining_names = list(grammar_names)
        remaining_weights = list(w)

        for _ in range(n):
            total = sum(remaining_weights)
            if total == 0:
                break
            probs = [x / total for x in remaining_weights]
            idx = random.choices(range(len(remaining_names)), weights=probs, k=1)[0]
            selected_names.append(remaining_names[idx])
            selected_fns.append(dict(all_grammars)[remaining_names[idx]])
            del remaining_names[idx]
            del remaining_weights[idx]

        use_glass = True
        print(f"  weights: {', '.join(f'{g}:{weights[g]:.1f}' for g in grammar_names)}")
        print(f"  fallback grammars: {' + '.join(selected_names)}")

    body_layers = ""
    css_extra = ""
    glass_html = ""
    glass_css = ""

    for fn in selected_fns:
        body, css, glass_h, glass_c = fn()
        body_layers += body
        css_extra += css
        if glass_h and not glass_html and use_glass:
            glass_html = glass_h
            glass_css = glass_c

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Amalgamma — {article_title}</title>
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:100vw;height:100vh;overflow:hidden;background:{bg}}}
{css_extra}
{glass_css}
.vig{{position:fixed;inset:0;z-index:6;pointer-events:none;background:radial-gradient(ellipse 75% 55% at 50% 48%,transparent 0%,transparent 55%,rgba(0,0,0,.55) 100%)}}
.src{{position:fixed;bottom:2.8vh;right:3vw;z-index:7;color:rgba(255,255,255,.45);font-size:.65rem;letter-spacing:.06em;opacity:.35;pointer-events:none;font-family:system-ui,-apple-system,sans-serif;animation:s_fade 89s ease-in-out infinite}}
@keyframes s_fade{{0%,100%{{opacity:.18}}50%{{opacity:.35}}}}
</style>
</head>
<body>
{body_layers}
{glass_html}
<div class="vig"></div>
<div class="src">current inspiration: {article_title}</div>
<script>
(() => {{
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const master = ctx.createGain();
  master.gain.value = 0;
  master.connect(ctx.destination);

  const drone = ctx.createOscillator();
  drone.type = 'sine';
  drone.frequency.value = 55;
  const droneLFO = ctx.createOscillator();
  droneLFO.type = 'sine';
  droneLFO.frequency.value = 0.07;
  const droneLFOGain = ctx.createGain();
  droneLFOGain.gain.value = 8;
  droneLFO.connect(droneLFOGain);
  droneLFOGain.connect(drone.frequency);
  droneLFO.start();
  const droneVol = ctx.createGain();
  droneVol.gain.value = 0.05;
  drone.connect(droneVol);
  droneVol.connect(master);
  drone.start();

  const noiseLen = ctx.sampleRate * 2;
  const noiseBuf = ctx.createBuffer(1, noiseLen, ctx.sampleRate);
  const data = noiseBuf.getChannelData(0);
  for (let i = 0; i < noiseLen; i++) data[i] = Math.random() * 2 - 1;
  const noise = ctx.createBufferSource();
  noise.buffer = noiseBuf;
  noise.loop = true;
  const noiseFilter = ctx.createBiquadFilter();
  noiseFilter.type = 'lowpass';
  noiseFilter.frequency.value = 300;
  noiseFilter.Q.value = 0.5;
  const noiseVol = ctx.createGain();
  noiseVol.gain.value = 0.02;
  noise.connect(noiseFilter);
  noiseFilter.connect(noiseVol);
  noiseVol.connect(master);
  noise.start();

  const pulse = ctx.createOscillator();
  pulse.type = 'sine';
  pulse.frequency.value = 28;
  const pulseVol = ctx.createGain();
  pulseVol.gain.value = 0;
  pulse.connect(pulseVol);
  pulseVol.connect(master);
  pulse.start();

  const pulseInterval = 8.3;
  function update(t) {{
    const wobble = 1 + Math.sin(t * 0.3) * 0.1 + Math.sin(t * 0.13) * 0.08;
    master.gain.value = wobble * 0.5;
    const p = (t % pulseInterval) / pulseInterval;
    pulseVol.gain.value = (p < 0.08 ? (1 - p / 0.08) * 0.08 : 0);
    requestAnimationFrame(update);
  }}

  function init() {{
    if (ctx.state === 'suspended') ctx.resume();
    requestAnimationFrame(update);
    document.removeEventListener('click', init);
  }}
  document.addEventListener('click', init);
  setTimeout(() => {{ if (ctx.state === 'suspended') ctx.resume(); requestAnimationFrame(update); }}, 500);
}})();
</script>
</body>
</html>""", " + ".join(selected_names)


# ── Grammar: atmospheric ───────────────────────────────────────────

def _atmospheric(palette, bg, intensity):
    p = _particles(palette)
    b = _bands(palette)
    return f"""<div class="atmo"></div>
<div class="bands">{b}</div>
<div class="pts">{p}</div>"""

def _css_atmospheric(palette):
    c1, c2, c3 = palette[0], palette[1] if len(palette) > 1 else palette[0], palette[2] if len(palette) > 2 else palette[0]
    return f""".atmo{{position:fixed;inset:0;z-index:1;pointer-events:none;background:radial-gradient(ellipse 120% 60% at 50% 45%,{c1}22 0%,transparent 70%),radial-gradient(ellipse 140% 50% at 50% 55%,{c2}22 0%,transparent 65%),radial-gradient(ellipse 100% 30% at 50% 50%,{c3}22 0%,transparent 100%);animation:a_atmo 47s ease-in-out infinite}}
@keyframes a_atmo{{0%,100%{{opacity:1}}50%{{opacity:.7}}}}
.pts{{position:fixed;inset:0;z-index:4;pointer-events:none}}
.bands{{position:fixed;inset:0;z-index:3;pointer-events:none}}
.band{{position:absolute;left:-2vw;width:104vw;filter:blur(calc(var(--b)*1px));animation:b_drift var(--d) ease-in-out infinite;animation-delay:var(--del);transform:skewY(var(--sk))}}
@keyframes b_drift{{0%,100%{{top:var(--y1);opacity:1}}33%{{top:var(--y2);opacity:.6}}66%{{top:var(--y3);opacity:.85}}}}
.pt{{position:absolute;width:var(--s);height:var(--s);border-radius:50%;background:var(--c);filter:blur(calc(var(--s)*.3));animation:p_glow var(--p) ease-in-out infinite;animation-delay:var(--del);left:var(--x);top:var(--y)}}
@keyframes p_glow{{0%,100%{{opacity:.15;transform:scale(.6)}}40%{{opacity:.7;transform:scale(1.8)}}70%{{opacity:.3;transform:scale(1)}}}}"""


# ── Grammar: strokes (lines, marks, gestures — Twombly, graphic) ──

def _strokes(palette, bg, intensity):
    c1, c2, c3 = palette[0], palette[1] if len(palette) > 1 else palette[0], palette[2] if len(palette) > 2 else palette[0]
    primes = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61]
    random.shuffle(primes)
    count = random.randint(8, 60)
    marks = []

    for i in range(count):
        x1 = random.uniform(-5, 105)
        y1 = random.uniform(-5, 105)
        # 60% straight lines, 30% slight curves, 10% sharp angles
        rtype = random.choices(["straight", "curve", "angle", "zigzag", "arc"], weights=[0.4, 0.25, 0.1, 0.15, 0.1], k=1)[0]
        base_angle = random.uniform(0, 360)
        if rtype == "straight":
            length = random.uniform(3, 50)
            x2 = x1 + length * math.cos(math.radians(base_angle))
            y2 = y1 + length * math.sin(math.radians(base_angle))
            path = f'M{x1:.1f},{y1:.1f}L{x2:.1f},{y2:.1f}'
        elif rtype == "curve":
            cx = x1 + random.uniform(-25, 25)
            cy = y1 + random.uniform(-30, 30)
            x2 = x1 + random.uniform(-40, 40)
            y2 = y1 + random.uniform(-40, 40)
            path = f'M{x1:.1f},{y1:.1f}Q{cx:.1f},{cy:.1f},{x2:.1f},{y2:.1f}'
        elif rtype == "angle":
            mx = x1 + random.uniform(-25, 25)
            my = y1 + random.uniform(-25, 25)
            x2 = mx + random.uniform(-25, 25)
            y2 = my + random.uniform(-25, 25)
            path = f'M{x1:.1f},{y1:.1f}L{mx:.1f},{my:.1f}L{x2:.1f},{y2:.1f}'
        elif rtype == "zigzag":
            pts = [(x1, y1)]
            for _ in range(random.randint(2, 4)):
                px = pts[-1][0] + random.uniform(-15, 15)
                py = pts[-1][1] + random.uniform(-15, 15)
                pts.append((px, py))
            path = "M" + " L".join(f"{p[0]:.1f},{p[1]:.1f}" for p in pts[1:])
            path = f'M{x1:.1f},{y1:.1f}L' + " L".join(f"{p[0]:.1f},{p[1]:.1f}" for p in pts[1:])
        else:  # arc
            rx = random.uniform(10, 40)
            ry = random.uniform(5, 25)
            rot = random.uniform(0, 360)
            sweep = random.choice([0, 1])
            x2 = x1 + random.uniform(-30, 30)
            y2 = y1 + random.uniform(-30, 30)
            path = f'M{x1:.1f},{y1:.1f}A{rx:.1f},{ry:.1f},{rot:.0f},0,{sweep},{x2:.1f},{y2:.1f}'

        sw = round(random.uniform(0.3, 6.0), 1)
        c = random.choice([c1, c2, c3])
        opacity = round(random.uniform(0.08, 0.45), 2)
        dash = "none"
        if random.random() < 0.35:
            dash = f"{random.randint(2,12)} {random.randint(3,15)}"
        if random.random() < 0.15:
            dash = f"{random.randint(1,3)} {random.randint(8,25)}"

        d = primes[i % len(primes)] / 2 + random.uniform(1, 8)
        dl = round(random.uniform(0, 20), 1)
        marks.append(
            f'<path d="{path}" stroke="{c}" stroke-width="{sw}" fill="none" '
            f'opacity="{opacity}" stroke-dasharray="{dash}" '
            f'style="animation:st_drift {d:.1f}s ease-in-out infinite;animation-delay:{dl:.1f}s;'
            f'stroke-linecap:{"round" if random.random()<0.7 else "butt"}"/>'
        )

    joined = "".join(marks)
    return f'<svg class="stf" viewBox="0 0 100 100" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">{joined}</svg>'


def _css_strokes(palette, bg):
    return f""".stf{{position:fixed;inset:0;z-index:2;pointer-events:none;width:100vw;height:100vh}}
@keyframes st_drift{{0%,100%{{opacity:var(--o,1);transform:translate(0,0)}}40%{{opacity:calc(var(--o,1)*1.6);transform:translate(1vw,-0.5vh)}}70%{{opacity:calc(var(--o,1)*0.6);transform:translate(-0.5vw,0.3vh)}}}}"""


# ── Grammar: field ──────────────────────────────────────────────────

def _field(palette, bg, intensity):
    count = random.randint(20, 300)
    field_particles = []
    primes = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97]
    random.shuffle(primes)
    for i in range(count):
        x = random.uniform(-10, 110)
        y = random.uniform(-10, 110)
        s = round(random.uniform(0.5, 6.0), 1)
        p_cycle = primes[i % len(primes)] / 5 + random.uniform(0, 3)
        delay = random.uniform(0, 20)
        c = random.choice(palette)
        if random.random() < 0.4:
            x = random.gauss(50, random.uniform(10, 50))
            y = random.gauss(50, random.uniform(10, 50))
        field_particles.append(
            f'<div class="fp" style="left:{x:.1f}%;top:{y:.1f}%;--s:{s}px;--p:{p_cycle:.1f}s;--del:{delay:.1f}s;--c:{c}"></div>'
        )
    return f'<div class="fpf">{"".join(field_particles)}</div>'

def _css_field(palette):
    return """.fpf{position:fixed;inset:0;z-index:2;pointer-events:none}
.fp{position:absolute;width:var(--s);height:var(--s);border-radius:50%;background:radial-gradient(circle,var(--c) 0%,transparent 70%);filter:blur(calc(var(--s)*.4));animation:f_breathe var(--p) ease-in-out infinite;animation-delay:var(--del)}
@keyframes f_breathe{0%,100%{opacity:.03;transform:scale(.8)}45%{opacity:.45;transform:scale(3)}75%{opacity:.15;transform:scale(1.4)}}"""


# ── Grammar: pulse ──────────────────────────────────────────────────

def _pulse(palette, bg, intensity):
    c1 = palette[0]
    c2 = palette[1] if len(palette) > 1 else c1
    forms = []
    count = random.randint(1, 6)
    sizes = [random.randint(20, 60) for _ in range(6)]
    blurs = [random.randint(3, 12) for _ in range(6)]
    cycles_p = [random.randint(29, 59) for _ in range(6)]
    for i in range(count):
        x = random.uniform(10, 85)
        y = random.uniform(10, 85)
        c = random.choice([c1, c2])
        forms.append(
            f'<div class="pf" style="left:{x:.0f}%;top:{y:.0f}%;width:{sizes[i]}vmin;height:{blurs[i]}vmin;background:radial-gradient(circle,{c}66 0%,{c}22 35%,transparent 70%);--p:{cycles_p[i]}s;--del:{-i*random.randint(1,5)}s"></div>'
        )
    return f'<div class="ppf">{"".join(forms)}</div>'

def _css_pulse(palette):
    return """.ppf{position:fixed;inset:0;z-index:2;pointer-events:none}
.pf{position:absolute;transform:translate(-50%,-50%);border-radius:50%;animation:p_beat var(--p) ease-in-out infinite;animation-delay:var(--del)}
@keyframes p_beat{0%,100%{transform:translate(-50%,-50%) scale(.7);opacity:.25}50%{transform:translate(-50%,-50%) scale(1.4);opacity:.7}}"""


# ── Grammar: liquid ─────────────────────────────────────────────────

def _liquid(palette, bg, intensity):
    c1, c2, c3 = palette[0], palette[1] if len(palette) > 1 else palette[0], palette[2] if len(palette) > 2 else palette[0]
    blobs = []
    count = random.randint(3, 20)
    primes = [43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97]
    random.shuffle(primes)
    for i in range(count):
        x = random.uniform(-30, 110)
        y = random.uniform(-30, 110)
        w = random.randint(10, 80)
        c = random.choice([c1, c2, c3])
        d = primes[i % len(primes)] / 2
        delay = random.uniform(0, 20)
        blobs.append(
            f'<div class="lb" style="left:{x:.0f}%;top:{y:.0f}%;width:{w}vmax;height:{w}vmax;background:radial-gradient(circle,{c}55 0%,{c}15 50%,transparent 75%);--d:{d:.1f}s;--del:{delay:.1f}s"></div>'
        )
    joined = "".join(blobs)
    return f'<div class="lbf">{joined}</div>'

def _css_liquid(palette):
    return """.lbf{position:fixed;inset:0;z-index:2;pointer-events:none;filter:blur(3vmax)}
.lb{position:absolute;border-radius:50%;transform:translate(-50%,-50%);animation:l_morph var(--d) ease-in-out infinite;animation-delay:var(--del)}
@keyframes l_morph{0%,100%{transform:translate(-50%,-50%) scale(.8) rotate(0deg);opacity:.25}33%{transform:translate(-50%,-50%) scale(1.3) rotate(15deg);opacity:.55}66%{transform:translate(-50%,-50%) scale(.6) rotate(-10deg);opacity:.35}}"""


# ── Glass layer ────────────────────────────────────────────────────

def _glass_layer():
    return """<div class="gls"></div>"""


def _css_glass():
    return """.gls{position:fixed;inset:0;z-index:5;pointer-events:none;mix-blend-mode:overlay;opacity:.04;animation:g_flick 47s steps(47) infinite}
.gls::before{content:"";position:absolute;inset:-20%;background:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E");background-size:256px 256px;animation:g_shift 17s linear infinite}
@keyframes g_shift{0%{transform:translate(0.0) rotate(0deg)}100%{transform:translate(-80px,40px) rotate(.7deg)}}
@keyframes g_flick{0%,100%{opacity:.03}50%{opacity:.07}}"""


# ── Shared helpers ──────────────────────────────────────────────────

def _particles(palette):
    count = random.randint(8, 120)
    particles = []
    primes = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97]
    random.shuffle(primes)
    phi = (1 + math.sqrt(5)) / 2
    for i in range(count):
        theta = 2 * math.pi * i / (phi ** 2)
        r_norm = math.sqrt(i / count)
        r = r_norm * 0.9
        x = 50 + r * 55 * math.cos(theta)
        y = 50 + r * 55 * math.sin(theta)
        if random.random() < 0.35:
            x += random.uniform(-40, 40)
            y += random.uniform(-40, 40)
        s = round(random.uniform(0.8, 8.0), 1)
        p = primes[i % len(primes)] / 4 + random.uniform(0, 4)
        delay = random.uniform(0, 15)
        c = random.choice(palette)
        particles.append(
            f'<div class="pt" style="--x:{x:.1f}%;--y:{y:.1f}%;--s:{s}px;--p:{p:.1f}s;--del:{delay:.1f}s;--c:{c}"></div>'
        )
    return "\n".join(particles)

def _bands(palette):
    count = random.randint(3, 25)
    bands = []
    primes = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59]
    random.shuffle(primes)
    for i in range(count):
        h = round(random.uniform(0.3, 6.0), 1)
        o = round(random.uniform(0.02, 0.25), 2)
        b = random.randint(2, 60)
        d = primes[i % len(primes)] / 2 + random.uniform(0, 5)
        delay = random.uniform(0, 20)
        sk = round(random.uniform(-2.0, 2.0), 1)
        y1 = random.randint(5, 85)
        y2 = random.randint(5, 85)
        y3 = random.randint(5, 85)
        c = random.choice(palette)
        hex_clean = c.lstrip("#")
        r, g, b_hex = int(hex_clean[0:2], 16), int(hex_clean[2:4], 16), int(hex_clean[4:6], 16)
        bands.append(
            f'<div class="band" style="--b:{b};--d:{d:.1f}s;--del:{delay:.1f}s;--sk:{sk}deg;--y1:{y1}vh;--y2:{y2}vh;--y3:{y3}vh;height:{h}vh;background:linear-gradient(90deg,rgba({r},{g},{b_hex},0) 0%,rgba({r},{g},{b_hex},{o}) 15%,rgba({r},{g},{b_hex},{o}) 50%,rgba({r},{g},{b_hex},{o}) 85%,rgba({r},{g},{b_hex},0) 100%)"></div>'
        )
    return "\n".join(bands)

# Glass CSS inlined in main generate_html for simplicity


# ── Palette shifter ─────────────────────────────────────────────────

def hex_to_hsl(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0
    cmax, cmin = max(r, g, b), min(r, g, b)
    delta = cmax - cmin
    l = (cmax + cmin) / 2
    if delta == 0:
        return 0, 0, l
    s = delta / (1 - abs(2 * l - 1))
    if cmax == r:
        h_val = ((g - b) / delta) % 6
    elif cmax == g:
        h_val = (b - r) / delta + 2
    else:
        h_val = (r - g) / delta + 4
    return h_val * 60, s, l


def hsl_to_hex(h, s, l):
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return f"#{(int((r+m)*255)):02x}{(int((g+m)*255)):02x}{(int((b+m)*255)):02x}"


def shift_palette(palette):
    shift = random.uniform(-45, 45)
    shifted = []
    for c in palette:
        try:
            h, s, l = hex_to_hsl(c)
            h = (h + shift + random.uniform(-15, 15)) % 360
            s = min(1.0, max(0.15, s + random.uniform(-0.15, 0.15)))
            l = min(0.85, max(0.10, l + random.uniform(-0.1, 0.1)))
            shifted.append(hsl_to_hex(h, s, l))
        except (ValueError, IndexError):
            shifted.append(c)
    return shifted


# ── Main ────────────────────────────────────────────────────────────

def main():
    temp = get_cycle_temp()
    state = read_state()
    print("[amalgamma] waking up")
    active = [f"{b['name']}{'$' if b['paid'] else ''}" for b in BACKENDS]
    if active:
        print(f"  backends: {', '.join(active)}")
    print(f"  temp: {temp}")
    print(f"  cycle: {state.get('cycle', 0)}")
    print()

    if not check_budget():
        print("  [stopped: budget exhausted]")
        return

    article = fetch_news()
    source_name = "rss"
    if not article:
        print("  [rss failed, trying wikipedia fallback]")
        article = fetch_wikipedia()
        source_name = "wikipedia"
    if not article:
        print("  [no article fetched]")
        return

    print(f"  source:  {source_name}")
    print(f"  article: {article['title']}")
    print(f"  {article.get('description', '')}")
    print()

    prompt = build_prompt(article)
    print("  sending prompt...")
    response = call_llm(prompt)
    print("  response received")
    print()

    try:
        response_clean = response.strip()
        if response_clean.startswith("```"):
            response_clean = re.sub(r"^```(?:json)?\s*", "", response_clean)
            response_clean = re.sub(r"\s*```$", "", response_clean)
        json_match = re.search(r'\{.*\}', response_clean, re.DOTALL)
        if json_match:
            vision = json.loads(json_match.group(0))
        else:
            print("  [no JSON in response, using fallback]")
            vision = {
                "bg": "#0a0a14",
                "palette": ["#b7f562", "#8b6fc0", "#e8dcc8", "#2a2540"],
                "mood": "quiet",
                "intensity": "medium",
                "gesture": "drifting particles floating through layered bands of colour",
                "structure": "atmospheric field with drifting particles and horizon bands",
                "motion": "slow breathing drift, bands rising and falling"
            }
        vision["palette"] = shift_palette(vision.get("palette", []))
        print(f"  mood: {vision.get('mood', '?')}")
        print(f"  palette: {', '.join(vision.get('palette', []))}")
    except json.JSONDecodeError:
        print("  [JSON parse failed, using fallback]")
        vision = {
            "bg": "#0a0a14",
            "palette": shift_palette(["#b7f562", "#8b6fc0", "#e8dcc8", "#2a2540"]),
            "mood": "quiet",
            "intensity": "medium",
            "gesture": "drifting particles floating through layered bands of colour",
            "structure": "atmospheric field with drifting particles and horizon bands",
            "motion": "slow breathing drift, bands rising and falling"
        }

    html, grammar = generate_html(vision, article["title"], article["url"], state.get("cycle", 0))

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = ARCHIVE_DIR / f"{timestamp}.html"
    archive_path.write_text(html, encoding="utf-8")
    print(f"  [saved] archive/{timestamp}.html")

    INDEX_PATH.write_text(html, encoding="utf-8")
    print(f"  [saved] index.html")
    print()

    state["cycle"] = state.get("cycle", 0) + 1
    state["last_title"] = article["title"]
    state["last_grammar"] = grammar
    state["archive_count"] = state.get("archive_count", 0) + 1
    write_state(state)

    active_str = f"{state['cycle']} cycles, {state['archive_count']} archived"
    print(f"  [{active_str}]")
    print()


if __name__ == "__main__":
    main()
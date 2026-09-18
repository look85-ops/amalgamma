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
                "max_tokens": 2500,
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
            "max_tokens": 2500,
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
                "maxOutputTokens": 2500,
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
                "max_tokens": 2500,
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

    return (
        f"Ты — художник. Пишешь картину кодом.\n\n"
        f"Твоя традиция: Ротко, Сулаж, Твомбли, Агнес Мартин, Малевич, Кандинский.\n"
        f"Язык: нефигуративный. Ритм. Тишина. Масштаб. Материальность.\n"
        f"Не красота — присутствие. Не декор — опыт.\n\n"
        f"Ты работаешь в браузере. Твой холст — HTML и CSS. Код — краска.\n"
        f"Полосы могут дышать. Блоки — весить. Пульсы — биться. Пятна — растекаться.\n"
        f"Пустота — не отсутствие, а структура. Меньше элементов — глубже присутствие.\n\n"
        f"Ниже — заголовок и фрагмент текста. Не иллюстрируй их.\n"
        f"Почувствуй вес, ритм, тишину. Найди форму для этого состояния.\n\n"
        f"Верни ТОЛЬКО HTML-код. Один <div> с инлайн-CSS. "
        f"Никаких скриптов, библиотек, комментариев, markdown-ограждений.\n"
        f"Это должна быть композиция, в которую можно войти. Не картинка. Пространство.\n\n"
        f"TITLE: {title}\n"
        f"TEXT: {extract}"
    )


# ── HTML wrapper ────────────────────────────────────────────────────

def generate_html(vision_html, article_title, cycle_num):
    vision_html = (vision_html or "").strip()

    # strip markdown fences
    if vision_html.startswith("```"):
        vision_html = re.sub(r"^```(?:html)?\s*", "", vision_html)
        vision_html = re.sub(r"\s*```$", "", vision_html)

    # check: does it look like HTML?
    if not vision_html or not vision_html.strip().startswith("<"):
        vision_html = (
            '<div style="position:fixed;inset:0;background:#0a0a14;'
            'display:flex;align-items:center;justify-content:center">'
            '<div style="width:40vw;height:40vh;background:#1a1a2e;'
            'opacity:.6;filter:blur(40px)"></div></div>'
        )
        print("  [fallback: LLM returned non-HTML]")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Amalgama — {article_title}</title>
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:100vw;height:100vh;overflow:hidden;background:#000}}
.artifact{{position:fixed;inset:0;z-index:1}}
.vig{{position:fixed;inset:0;z-index:10;pointer-events:none;background:radial-gradient(ellipse 75% 55% at 50% 48%,transparent 0%,transparent 55%,rgba(0,0,0,.4) 100%)}}
.src{{position:fixed;bottom:2.8vh;left:2.8vw;z-index:12;color:rgba(255,255,255,.6);font-size:.7rem;letter-spacing:.04em;pointer-events:none;font-family:system-ui,sans-serif;animation:s_fade 89s ease-in-out infinite;max-width:60vw;line-height:1.4;text-shadow:0 0 8px rgba(0,0,0,.5)}}
@keyframes s_fade{{0%,100%{{opacity:.25}}50%{{opacity:.5}}}}
</style>
</head>
<body>
<div class="artifact">{vision_html}</div>
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
  droneVol.gain.value = 0.04;
  drone.connect(droneVol);
  droneVol.connect(master);
  drone.start();
  const noiseLen = ctx.sampleRate * 2;
  const noiseBuf = ctx.createBuffer(1, noiseLen, ctx.sampleRate);
  const ndata = noiseBuf.getChannelData(0);
  for (let i = 0; i < noiseLen; i++) ndata[i] = Math.random() * 2 - 1;
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
  function update(t) {{
    const w = 1 + Math.sin(t * 0.3) * 0.08 + Math.sin(t * 0.13) * 0.06;
    master.gain.value = w * 0.35;
    const p = (t % 8.3) / 8.3;
    pulseVol.gain.value = (p < 0.08 ? (1 - p / 0.08) * 0.06 : 0);
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
</html>"""


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
    print("[amalgama] waking up")
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
    print(f"  response: {len(response)} chars")
    print()

    vision_html = response.strip()

    # retry once if it doesn't look like HTML
    if not vision_html.startswith("<"):
        print("  [response not HTML, retrying...]")
        response = call_llm(prompt)
        vision_html = response.strip()

    html = generate_html(vision_html, article["title"], state.get("cycle", 0))

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
    state["archive_count"] = state.get("archive_count", 0) + 1
    write_state(state)

    active_str = f"{state['cycle']} cycles, {state['archive_count']} archived"
    print(f"  [{active_str}]")
    print()


if __name__ == "__main__":
    main()
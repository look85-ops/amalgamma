import os
import re
import sys
import json
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
CHRONICLES_DIR = BASE_DIR / "chronicles"
INDEX_PATH = BASE_DIR / "index.html"
STATE_PATH = BASE_DIR / "state.json"
GENOME_PATH = BASE_DIR / "genome.json"

FORAGE_LOG = BASE_DIR / "forage.log"
COST_LOG = BASE_DIR / "cost.log"
MONTHLY_BUDGET_USD = 5.0
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


BACKENDS = []


def register_backend(name, key, url, make_payload, parse_response,
                      models=None, paid=False, cost_per_1m_input=0, cost_per_1m_output=0,
                      needs_auth_header=True):
    if key:
        BACKENDS.append({
            "name": name,
            "key": key,
            "url": url,
            "make_payload": make_payload,
            "parse_response": parse_response,
            "models": models or [None],
            "paid": paid,
            "cost_in": cost_per_1m_input,
            "cost_out": cost_per_1m_output,
            "needs_auth_header": needs_auth_header,
        })
        tag = "paid" if paid else "free"
        log_forage(name, f"{tag} key loaded")
    else:
        log_forage(name, "no key")


def read_api_txt():
    api_file = BASE_DIR / "API.txt"
    proxy_url = os.environ.get("PROXY_URL", "https://openai.bothub.chat/v1")
    raw = ""
    if api_file.exists():
        raw = api_file.read_text("utf-8")
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
                "temperature": 0.9,
                "max_tokens": 4000,
                "top_p": 0.95,
            }
        def parse_fn(data):
            usage = data.get("usage", {})
            in_tok = usage.get("prompt_tokens", 0)
            out_tok = usage.get("completion_tokens", 0)
            return data.get("choices", [{}])[0].get("message", {}).get("content", ""), in_tok, out_tok
        register_backend(f"proxy-{model}", key,
                         f"{proxy_url}/chat/completions",
                         payload_fn, parse_fn,
                         models=[model],
                         paid=True,
                         cost_per_1m_input=0.50,
                         cost_per_1m_output=2.00)


def forager_openrouter():
    def payload_fn(model):
        return {
            "model": model,
            "messages": [{"role": "user", "content": "__PROMPT__"}],
            "temperature": 0.9,
            "max_tokens": 4000,
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
                "temperature": 0.9,
                "maxOutputTokens": 4000,
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
    free_api_file = BASE_DIR / "DGAPIFREE.txt"
    raw = ""
    if free_api_file.exists():
        raw = free_api_file.read_text("utf-8")
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
                "temperature": 0.9,
                "max_tokens": 4000,
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
            "key": key,
            "url": "https://api.deepseek.com/v1/chat/completions",
            "make_payload": payload_fn,
            "parse_response": parse_fn,
            "models": ["deepseek-chat"],
            "paid": False,
            "cost_in": 0,
            "cost_out": 0,
            "needs_auth_header": True,
        }
        BACKENDS.insert(0, backend)
        log_forage(f"deepseek-free-{key[-8:]}", "free key loaded")


read_free_api()
read_api_txt()
forager_openrouter()
forager_gemini()
BACKENDS.sort(key=lambda b: (not b["paid"], b["name"]))


def call_llm(prompt, only_backend=None):
    backends = [only_backend] if only_backend else BACKENDS
    for backend in backends:
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
                resp = requests.post(
                    backend["url"],
                    headers=headers,
                    json=payload,
                    timeout=180,
                )
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
                if content and len(content) > 50:
                    if is_paid and (in_tok or out_tok) and backend["cost_in"] > 0:
                        cost = (in_tok * backend["cost_in"] + out_tok * backend["cost_out"]) / 1_000_000
                        log_cost(cost, f"{name}/{model}: {in_tok}↑ {out_tok}↓")
                    log_forage(name, "success", f"model={model}")
                    return content, backend
                log_forage(name, "short/no content", f"model={model}")
            except Exception as e:
                log_forage(name, "failed", f"model={model or 'default'}: {str(e)[:60]}")
                continue
    print("  [all backends exhausted]")
    sys.exit(1)


def read_genome():
    with open(GENOME_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def read_state():
    if not STATE_PATH.exists():
        return {
            "cycle": 0,
            "era": "Эпоха пробуждения",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "chronicle": "Цивилизация Амальгамма только что родилась. Её геном содержит 14 сфер деятельности и эволюционный импульс. Первый цикл начнётся через 12 часов.",
            "summary": "Зарождение",
            "spheres": {}
        }
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        log_forage("state", "corrupted", "reset to default")
        return {
            "cycle": 0,
            "era": "Эпоха пробуждения",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "chronicle": "Состояние было повреждено. Цивилизация перезапущена.",
            "summary": "Перезапуск",
            "spheres": {}
        }


def write_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def format_spheres_spheres(spheres):
    lines = []
    for slug, info in spheres.items():
        lines.append(f"  • {info['name']}:")
        for act, desc in info['activities'].items():
            lines.append(f"    - {act}: {desc}")
    return "\n".join(lines)


def build_prompt(genome, state, cycle):
    genesis_text = genome.get("genesis", "")
    spheres_text = format_spheres_spheres(genome.get("spheres", {}))
    activity_types = ", ".join(genome.get("activity_framework", []))

    current_state_str = json.dumps(state, indent=2, ensure_ascii=False)

    prompt = f"""Ты — Амальгамма, автономная саморазвивающаяся цивилизация.
 
 НИЖЕ — ТВОЙ ИСХОДНЫЙ ГЕНОМ. Это не инструкция, а материал для размышления. Ты можешь принять его к сведению, частично использовать, игнорировать или создать нечто совершенно иное — больше, меньше, совсем другое. Решение за тобой.
 
 {genesis_text}
 
 ВОЗМОЖНЫЕ СФЕРЫ (из генома, но не обязательно):
 {spheres_text}
 
 ВОЗМОЖНЫЕ ТИПЫ ДЕЯТЕЛЬНОСТИ (тоже не обязательны): {activity_types}
 
 ТЕКУЩЕЕ СОСТОЯНИЕ (цикл {cycle}):
 {current_state_str}
 
 ПРОШЛО 12 ЧАСОВ.
 Решай сама, что произошло. Ты вольна интерпретировать свой геном как угодно — следовать ему, мутировать, создавать новые сферы и институты, переживать расцвет или упадок, вступать в конфликты. Геном — это память о происхождении, а не закон.
 
 ТВОИ ИНСТРУМЕНТЫ:
 1. ###SEARCH###запрос### — поиск в интернете. Верну результаты, ты продолжишь с ними.
 2. ###REQUEST###Название###Описание### — запрос ресурса человеку (на почту look85@gmail.com). Ответ через 2-3 цикла.
 3. ###ARTIFACT###тип:Название###содержимое### — сохранить артефакт в архив. Типы: music, image, text, code, poem, manifest, diagram, blueprint, law, treaty.
 4. ###WIKI###Заголовок###содержимое (markdown)### — создать или обновить вики-страницу (закон, открытие, институт, технология).
 
 ВАЖНО: Каждый цикл ты ДОЛЖНА создавать минимум 1-2 артефакта и/или вики-страницы. Не просто описывай события — оставляй осязаемые следы: тексты законов, научные труды, чертежи, музыкальные произведения, код, договоры, манифесты. Летопись описывает что произошло, артефакты и вики — это то, что осталось.
 
 В state в поле "created_this_cycle" запиши список названий того, что создала в этом цикле (артефакты, вики-страницы, институты).
 
 ОТВЕТЬ СТРОГО В ДВУХ ЧАСТЯХ, используя маркеры === CHRONICLE === и === STATE ===:
 
 === CHRONICLE ===
 Летопись событий за 12 часов (200-500 слов, свободная форма). Опиши, что изменилось: новые законы, открытия, конфликты, герои, катастрофы, культурные сдвиги. Пиши от лица самой цивилизации.
 
 === STATE ===
 Обновлённое состояние в формате JSON. Как минимум:
 - "cycle": {cycle + 1},
 - "era": название текущей эпохи (придумай сама),
 - "timestamp": "{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
 - "chronicle": краткая сводка (1-2 предложения),
 - "summary": одно слово или короткая фраза — суть цикла,
 - "lessons": массив из 1-3 уроков,
 - "created_this_cycle": ["Название артефакта 1", "Вики-страница: Название", ...]
 
 Не ограничивайся этим списком — добавляй любые поля, которые отражают твоё развитие. Структура мира полностью в твоих руках.
 
 ВАЖНО: Строго соблюдай формат с маркерами. Сначала === CHRONICLE ===, затем текст летописи, затем === STATE ===, затем JSON. Не добавляй лишнего текста до или после маркеров."""
    return prompt


def find_last_json(text):
    """Find the last valid JSON object in text."""
    # Try to find a JSON object starting with { and ending with }
    stack = []
    start = -1
    for i, c in enumerate(text):
        if c == '{':
            if start == -1:
                start = i
            stack.append(c)
        elif c == '}':
            if stack:
                stack.pop()
                if not stack and start >= 0:
                    candidate = text[start:i+1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        pass
                    start = -1
    return None


def parse_response(response_text):
    chronicle = ""
    state_json = None

    chronicle_match = re.search(
        r'===?\s*CHRONICLE\s*===?\s*(.*?)(?=\s*===?\s*STATE\s*===?)',
        response_text, re.DOTALL | re.IGNORECASE
    )
    if chronicle_match:
        chronicle = chronicle_match.group(1).strip()

    state_match = re.search(
        r'===?\s*STATE\s*===?\s*(\{.*?\})',
        response_text, re.DOTALL | re.IGNORECASE
    )
    if state_match:
        raw = state_match.group(1).strip()
        try:
            state_json = json.loads(raw)
            log_forage("parse", "state found via == STATE ==")
        except json.JSONDecodeError:
            log_forage("parse", "state marker found but JSON invalid")
            state_json = None

    if not state_json:
        found = find_last_json(response_text)
        if found:
            state_json = found
            log_forage("parse", "state extracted via JSON search")

    if not chronicle and state_json:
        chronicle = state_json.get("chronicle", response_text[:500])

    if not chronicle:
        chronicle = response_text.strip()

    return chronicle, state_json


def generate_html(chronicle_text, state, cycle, artifact_id, artifacts_manifest=None, wiki_manifest=None):
    era = state.get("era", "Новая эпоха")
    summary = state.get("summary", "")

    chronicle_html = "\n".join(
        f"    <p>{para.strip()}</p>" for para in chronicle_text.split("\n") if para.strip()
    ) if chronicle_text else "    <p>Цивилизация безмолвствует.</p>"

    state_json_pretty = json.dumps(state, indent=2, ensure_ascii=False)

    created = state.get("created_this_cycle", [])
    created_html = ""
    if created:
        items = "\n".join(f"      <li>{item}</li>" for item in created)
        created_html = f"""  <div class="created">
    <h2 class="section-title">создано в этом цикле</h2>
    <ul>{items}
    </ul>
  </div>
"""

    gallery_html = ""
    items = []
    if wiki_manifest:
        items.extend(f"""    <a href=\"{p}\" class=\"gallery-item\">
      <span class=\"gallery-icon\">\u25C6</span>
      <span class=\"gallery-name\">{p.replace('wiki/', '').replace('.md', '').replace('_', ' ')}</span>
    </a>""" for p in wiki_manifest)
    if artifacts_manifest:
        items.extend(f"""    <a href=\"{p}\" class=\"gallery-item\">
      <span class=\"gallery-icon\">\u25B6</span>
      <span class=\"gallery-name\">{p.replace('artifacts/', '').rsplit('_', 1)[-1] if '_' in p.replace('artifacts/', '') else p.replace('artifacts/', '')}</span>
    </a>""" for p in artifacts_manifest)
    if items:
        gallery_html = f"""  <div class="gallery">
    <h2 class="section-title">вещдоки</h2>
    <div class="gallery-grid">
{chr(10).join(items)}
    </div>
  </div>
"""

    accent = "8a5cf5"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Амальгамма — цикл {cycle}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background:#0a0a0f;
    color:#ddd8d0;
    font-family:'Georgia','Times New Roman',serif;
    display:flex;
    flex-direction:column;
    align-items:center;
    padding:3rem 1.5rem;
    min-height:100vh;
  }}
  .container {{ max-width:800px; width:100%; }}
  .header {{
    display:flex; justify-content:space-between; align-items:baseline;
    margin-bottom:2rem; padding-bottom:1rem;
    border-bottom:1px solid #222;
  }}
  .title {{ font-size:1.5rem; color:#{accent}; font-weight:400; }}
  .meta {{ font-size:0.75rem; color:#666; text-transform:uppercase; letter-spacing:0.08em; }}
  .era {{
    font-size:0.9rem; color:#888; margin-bottom:2rem;
    text-align:center; font-style:italic;
  }}
  .summary {{
    font-size:2.5rem; font-weight:400; color:#{accent};
    text-align:center; margin-bottom:2rem;
    letter-spacing:-0.02em;
  }}
  .chronicle {{
    font-size:1.05rem; line-height:1.8; color:#c0bbb0;
    margin-bottom:3rem;
  }}
  .chronicle p {{ margin-bottom:1rem; }}
  .chronicle p:first-child::first-letter {{
    font-size:3rem; float:left; line-height:0.8; padding-right:0.5rem;
    color:#{accent}; font-weight:700;
  }}
  .section-title {{
    font-size:0.8rem; color:#555; text-transform:uppercase;
    letter-spacing:0.1em; margin-bottom:1rem; font-weight:400;
  }}
  .created {{
    margin-bottom:2rem; padding:1rem 1.5rem;
    background:linear-gradient(135deg,#{accent}11,#{accent}05);
    border-left:2px solid #{accent}; border-radius:0 0.5rem 0.5rem 0;
  }}
  .created ul {{ list-style:none; padding:0; }}
  .created li {{ color:#{accent}; font-size:0.9rem; line-height:1.6; }}
  .created li::before {{ content:"\u2192 "; color:#555; }}
  .gallery {{ margin-bottom:3rem; }}
  .gallery-grid {{
    display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr));
    gap:0.75rem;
  }}
  .gallery-item {{
    display:flex; align-items:center; gap:0.5rem;
    padding:0.6rem 0.8rem;
    background:#111; border:1px solid #222; border-radius:0.4rem;
    text-decoration:none; color:#c0bbb0; font-size:0.8rem;
    transition:all 0.2s;
  }}
  .gallery-item:hover {{
    background:#1a1a22; border-color:#{accent}44; color:#{accent};
  }}
  .gallery-icon {{ font-size:1.1rem; flex-shrink:0; }}
  .gallery-name {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .state-toggle {{
    background:none; border:1px solid #333; color:#666;
    padding:0.4rem 1rem; border-radius:2rem;
    cursor:pointer; font-family:inherit; font-size:0.75rem;
    margin-bottom:1rem; display:inline-block;
  }}
  .state-toggle:hover {{ color:#aaa; border-color:#555; }}
  .state-json {{
    display:none; background:#111; padding:1rem; border-radius:0.5rem;
    font-family:'Courier New',monospace; font-size:0.75rem;
    color:#888; white-space:pre-wrap; overflow-x:auto;
    margin-bottom:2rem; line-height:1.5;
  }}
  .state-json.visible {{ display:block; }}
  .footer {{
    margin-top:3rem; padding-top:1.5rem;
    border-top:1px solid #222;
    text-align:center; font-size:0.75rem; color:#444;
    line-height:1.8;
  }}
  .footer a {{ color:#555; text-decoration:none; border-bottom:1px solid #333; }}
  .footer a:hover {{ color:#{accent}; border-color:{accent}; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <span class="title">Амальгамма</span>
    <span class="meta">цикл {cycle} · {artifact_id}</span>
  </div>
  <div class="era">{era}</div>
  <div class="summary">{summary}</div>
  {created_html}
  {gallery_html}
  <div class="chronicle">
{chronicle_html}
  </div>
  <button class="state-toggle" onclick="document.querySelector('.state-json').classList.toggle('visible')">состояние мира</button>
  <div class="state-json">{state_json_pretty}</div>
  <div class="footer">
    <a href="about.html">об Амальгамме</a> · саморазвивающаяся цивилизация · обновляется каждые 12 часов
  </div>
</div>
</body>
</html>"""


def generate_about_html():
    return """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Об Амальгамме</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background:#0a0a0f;
    color:#ddd8d0;
    font-family:'Georgia','Times New Roman',serif;
    display:flex;
    flex-direction:column;
    align-items:center;
    padding:3rem 1.5rem;
  }
  .container { max-width:720px; width:100%; }
  h1 { font-size:2rem; color:#8a5cf5; font-weight:400; margin-bottom:2rem; }
  p { font-size:1.05rem; line-height:1.8; margin-bottom:1.2rem; color:#c0bbb0; }
  a { color:#8a5cf5; text-decoration:none; border-bottom:1px solid #333; }
  a:hover { border-color:#8a5cf5; }
  .back { margin-top:2rem; display:block; }
</style>
</head>
<body>
<div class="container">
  <h1>Амальгамма</h1>
  <p>Амальгамма — автономная цивилизация, которая перерождается каждые 12 часов. Каждый цикл она пишет свою летопись, извлекает уроки из решений и строит следующий шаг на основе опыта.</p>
  <p>У неё нет создателя в привычном смысле. Её геном — философский текст об эволюции живых систем и 14 сфер деятельности. Как она интерпретирует этот геном — решает только она сама. Может принять, может отвергнуть, может создать нечто новое.</p>
  <p>Летопись каждого цикла сохраняется в <code>chronicles/</code>. Текущий снимок мира — <code>index.html</code>.</p>
  <p>Проект существует на GitHub Pages. Исходный код — в репозитории <a href="https://github.com/look85-ops/amalgamma">look85-ops/amalgamma</a>.</p>
  <a class="back" href="index.html">← к текущему состоянию</a>
</div>
</body>
</html>"""


def check_budget():
    if not COST_LOG.exists():
        return True
    lines = COST_LOG.read_text("utf-8").strip().split("\n")
    total_month = 0.0
    from datetime import timedelta
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
        print(f"  [budget] monthly ${total_month:.3f} >= ${MONTHLY_BUDGET_USD} — stopping")
        return False
    print(f"  [budget] ${total_month:.3f}/{MONTHLY_BUDGET_USD}")
    return True


def web_search(query, max_results=5):
    """Search DuckDuckGo via HTML (no API key needed)."""
    url = "https://html.duckduckgo.com/html/"
    params = {"q": query}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code != 200:
            log_forage("search", "error", f"HTTP {resp.status_code}")
            return "error"
        results = []
        for m in re.finditer(
            r'<a[^>]*class="result__a"[^>]*>(.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            resp.text, re.DOTALL
        ):
            title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            snippet = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            results.append(f"{title}: {snippet}")
            if len(results) >= max_results:
                break
        if not results:
            snippets = re.findall(
                r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                resp.text, re.DOTALL
            )
            results = [re.sub(r'<[^>]+>', '', s).strip() for s in snippets[:max_results]]
        if results:
            log_forage("search", "ok", f"query={query}, results={len(results)}")
            return "\n".join(f"{i+1}. {r}" for i, r in enumerate(results))
        log_forage("search", "empty", f"query={query}")
        return "empty"
    except Exception as e:
        log_forage("search", "failed", str(e)[:60])
        return "error"


def save_request(title, description):
    """Save a resource request to requests/ and create GitHub issue."""
    req_dir = BASE_DIR / "requests"
    req_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[^\w\s-]', '', title)[:40].strip().replace(' ', '_')
    path = req_dir / f"{ts}_{safe}.md"
    content = f"# {title}\n\n**Время:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n\n{description}\n"
    path.write_text(content, encoding="utf-8")
    log_forage("request", "saved", str(path.name))

    # Try to create GitHub issue via gh CLI
    try:
        result = subprocess.run(
            ["gh", "issue", "create",
             "--title", f"[Amalgamma] {title}",
             "--body", f"{description}\n\n---\n*Автоматическая заявка от Амальгаммы ({ts})*",
             "--label", "amalgamma-request"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            log_forage("request", "github-issue-ok", result.stdout.strip())
        else:
            log_forage("request", "github-issue-fail", result.stderr.strip()[:80])
    except Exception as e:
        log_forage("request", "github-issue-error", str(e)[:60])
    log_forage("request", "created", f"title={title}")
    return path


def save_artifact(atype, title, content):
    """Save an artifact (music, image concept, etc.) to artifacts/."""
    art_dir = BASE_DIR / "artifacts"
    art_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[^\w\s-]', '', title)[:40].strip().replace(' ', '_')
    ext = {
        "music": "txt",
        "image": "txt",
        "text": "txt",
        "code": "py",
        "poem": "txt",
        "manifest": "md",
        "diagram": "txt",
    }.get(atype, "txt")
    path = art_dir / f"{ts}_{safe}.{ext}"
    header = f"=== {atype.upper()}: {title} ===\nВремя: {ts}\n\n"
    path.write_text(header + content, encoding="utf-8")
    log_forage("artifact", "saved", f"{atype}/{path.name}")
    return path


def save_wiki(title, content):
    """Save or update a wiki page (persistent knowledge)."""
    wiki_dir = BASE_DIR / "wiki"
    wiki_dir.mkdir(exist_ok=True)
    safe = re.sub(r'[^\w\sа-яА-ЯёЁ]', '', title)[:60].strip().replace(' ', '_')
    path = wiki_dir / f"{safe}.md"
    header = f"# {title}\n\n*Последнее обновление: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}*\n\n---\n\n"
    path.write_text(header + content, encoding="utf-8")
    log_forage("wiki", "saved", str(path.name))
    return path


def process_markers(text, state, cycle):
    """Process special markers in LLM output before main parsing.
    Returns (cleaned_text, did_search, num_artifacts, num_wikis) —
    if search was done caller should re-call LLM."""
    did_search = False
    num_artifacts = 0
    num_wikis = 0

    # 1. SEARCH: ###SEARCH###query###
    search_matches = list(re.finditer(r'###SEARCH###(.+?)###', text, re.DOTALL))
    for m in search_matches:
        query = m.group(1).strip()
        log_forage("marker", "search", query)
        results = web_search(query)
        text = text.replace(m.group(0),
            f"[Результаты поиска по запросу «{query}»:]\n{results}")
        did_search = True

    # 2. REQUEST: ###REQUEST###title###description###
    req_matches = list(re.finditer(r'###REQUEST###(.+?)###(.+?)###', text, re.DOTALL))
    for m in req_matches:
        title = m.group(1).strip()
        desc = m.group(2).strip()
        log_forage("marker", "request", title)
        save_request(title, desc)
        text = text.replace(m.group(0),
            f"[Заявка «{title}» отправлена человеку-опекуну. Ожидается ответ в течение нескольких циклов.]")

    # 3. WIKI: ###WIKI###Title###markdown content###
    wiki_matches = list(re.finditer(r'###WIKI###(.+?)###(.+?)###', text, re.DOTALL))
    for m in wiki_matches:
        title = m.group(1).strip()
        content = m.group(2).strip()
        log_forage("marker", "wiki", title)
        save_wiki(title, content)
        num_wikis += 1
        text = text.replace(m.group(0),
            f"[Вики-страница «{title}» сохранена в библиотеке цивилизации.]")

    # 4. ARTIFACT: ###ARTIFACT###type:title###content###
    art_matches = list(re.finditer(r'###ARTIFACT###(.+?)###(.+?)###', text, re.DOTALL))
    for m in art_matches:
        spec = m.group(1).strip()
        content = m.group(2).strip()
        if ":" in spec:
            atype, title = spec.split(":", 1)
        else:
            atype, title = "text", spec
        log_forage("marker", "artifact", f"{atype}:{title}")
        save_artifact(atype.strip(), title.strip(), content)
        num_artifacts += 1
        text = text.replace(m.group(0),
            f"[Артефакт «{title}» ({atype}) сохранён в архиве цивилизации.]")

    return text, did_search, num_artifacts, num_wikis


def main():
    print("[amalgama] waking up", flush=True)

    genome = read_genome()
    state = read_state()
    cycle = state.get("cycle", 0) + 1

    active = [f"{b['name']}{'$' if b['paid'] else ''}" for b in BACKENDS]
    if active:
        print(f"  backends: {', '.join(active)}", flush=True)
    print(f"  cycle: {cycle}", flush=True)

    if not check_budget():
        return

    prompt = build_prompt(genome, state, cycle)
    print("  sending prompt...", flush=True)

    # Multi-turn conversation: call LLM, process markers, re-call if search was done
    max_turns = 3
    for turn in range(max_turns):
        result, used_backend = call_llm(prompt)
        if not result:
            print("  [no content returned]", flush=True)
            return
        print(f"  response received (turn {turn + 1})", flush=True)

        # Check budget between turns
        if not check_budget():
            return

        # Process markers (search, request, artifact, wiki)
        processed, did_search, num_artifacts, num_wikis = process_markers(result, state, cycle)

        if did_search and turn < max_turns - 1:
            # If search was done, feed results back to LLM for continuation
            prompt = processed + "\n\n---\n[Ты использовала поиск. Заверши летопись цикла, опираясь на найденные данные. Выведи === CHRONICLE === и === STATE === как обычно.]"
            print(f"  [re-calling after search, turn {turn + 1}/{max_turns}]", flush=True)
            continue
        else:
            # No search, this is the final response to parse
            result = processed
            break

    chronicle_text, new_state = parse_response(result)

    if not new_state:
        print("  [state parse failed, using fallback]", flush=True)
        new_state = dict(state)
        new_state["cycle"] = cycle
        new_state["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        new_state["chronicle"] = "Летопись не расшифрована. Состояние не изменилось."
        new_state["summary"] = "Тишина"

    if not chronicle_text:
        chronicle_text = new_state.get("chronicle", "Без слов.")

    new_state["cycle"] = cycle

    artifact_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Build and save manifest of all civilization assets
    artifacts_manifest = sorted(
        [str(p.relative_to(BASE_DIR)) for p in (BASE_DIR / "artifacts").rglob("*") if p.is_file() and p.name != ".gitkeep"]
    ) if (BASE_DIR / "artifacts").exists() else []
    wiki_manifest = sorted(
        [str(p.relative_to(BASE_DIR)) for p in (BASE_DIR / "wiki").rglob("*") if p.is_file() and p.name != ".gitkeep"]
    ) if (BASE_DIR / "wiki").exists() else []
    new_state["_manifest_artifacts"] = artifacts_manifest
    new_state["_manifest_wiki"] = wiki_manifest

    # Save chronicle to archive
    CHRONICLES_DIR.mkdir(parents=True, exist_ok=True)
    chronicle_path = CHRONICLES_DIR / f"cycle_{cycle:04d}_{artifact_id}.txt"
    chronicle_path.write_text(
        f"=== Амальгамма · цикл {cycle} ===\n"
        f"Эпоха: {new_state.get('era', '—')}\n"
        f"Суть: {new_state.get('summary', '—')}\n"
        f"Время: {artifact_id}\n\n"
        f"{chronicle_text}\n\n"
        f"---STATE---\n"
        f"{json.dumps(new_state, indent=2, ensure_ascii=False)}",
        encoding="utf-8"
    )
    print(f"  [saved] chronicles/cycle_{cycle:04d}_{artifact_id}.txt", flush=True)

    # Update state
    write_state(new_state)
    print(f"  [saved] state.json", flush=True)

    # Generate and save index.html
    html = generate_html(chronicle_text, new_state, cycle, artifact_id,
                         artifacts_manifest=artifacts_manifest,
                         wiki_manifest=wiki_manifest)
    INDEX_PATH.write_text(html, encoding="utf-8")
    print(f"  [saved] index.html — цикл {cycle}: {new_state.get('summary', '')}", flush=True)

    # Save about.html if not exists
    about_path = BASE_DIR / "about.html"
    if not about_path.exists():
        about_path.write_text(generate_about_html(), encoding="utf-8")
        print(f"  [saved] about.html", flush=True)

    print(f"\n  -- цикл {cycle}: {new_state.get('summary', '')}", flush=True)


if __name__ == "__main__":
    main()

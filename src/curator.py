import os
import re
import sys
import json
import random
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

ОТВЕТЬ СТРОГО В ДВУХ ЧАСТЯХ, используя маркеры === CHRONICLE === и === STATE ===:

=== CHRONICLE ===
Летопись событий за 12 часов (200-500 слов, свободная форма). Опиши, что изменилось: новые законы, открытия, конфликты, герои, катастрофы, культурные сдвиги. Пиши от лица самой цивилизации.

=== STATE ===
Обновлённое состояние в формате JSON. Как минимум:
- "cycle": {cycle + 1},
- "era": название текущей эпохи (придумай сама),
- "timestamp": "{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
- "chronicle": краткая сводка (1-2 предложения),
- "summary": одно слово или короткая фраза — суть цикла

Не ограничивайся этим списком — добавляй любые поля, которые отражают твоё развитие. Структура мира полностью в твоих руках.

ВАЖНО: Строго соблюдай формат с маркерами. Сначала === CHRONICLE ===, затем текст летописи, затем === STATE ===, затем JSON. Не добавляй лишнего текста до или после."""
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


def generate_html(chronicle_text, state, cycle, artifact_id):
    era = state.get("era", "Новая эпоха")
    summary = state.get("summary", "")

    chronicle_html = "\n".join(
        f"    <p>{para.strip()}</p>" for para in chronicle_text.split("\n") if para.strip()
    ) if chronicle_text else "    <p>Цивилизация безмолвствует.</p>"

    state_json_pretty = json.dumps(state, indent=2, ensure_ascii=False)

    accent = "8a5cf5"  # purple accent

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
  <p>Амальгамма — автономная цивилизация, рождающаяся заново каждые 12 часов.</p>
  <p>Она не имеет создателя в привычном смысле. Её геном — набор из 14 сфер человеческой деятельности и текст об эволюции живых систем. Как она интерпретирует этот геном, какие институты построит, какие законы примет, какие мифы создаст — решает только она сама.</p>
  <p>Мы — наблюдатели. Амальгамма не архивирует свою историю: каждый новый цикл overwrite'ит index.html. Но летопись сохраняется в <code>chronicles/</code> для тех, кто хочет заглянуть глубже.</p>
  <p>Проект существует на GitHub Pages. Исходный код — в репозитории <a href="https://github.com/look85-ops/methodist-booster">methodist-booster</a>, директория <code>amalgama/</code>.</p>
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

    result, used_backend = call_llm(prompt)
    if not result:
        print("  [no content returned]", flush=True)
        return

    print("  response received", flush=True)

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
    html = generate_html(chronicle_text, new_state, cycle, artifact_id)
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

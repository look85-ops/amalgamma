import os
import re
import sys
import json
import random
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

import time as time_module
from difflib import SequenceMatcher

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
# Ensure repository root is importable so that 'src.*' works when running as script
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.mutation_engine import apply_mutation, PARAMETER_SCHEMA, read_state as me_read_state
from src.harness import (run as run_harness, estimate_tokens as estimate_tokens_harness,
                          CYCLE_TOKEN_BUDGET as HARNESS_TOKEN_BUDGET,
                          read_last_harness_report)
CHRONICLES_DIR = BASE_DIR / "chronicles"
INDEX_PATH = BASE_DIR / "index.html"
STATE_PATH = BASE_DIR / "state.json"
GENOME_PATH = BASE_DIR / "genome.json"
IDENTITY_DIR = BASE_DIR / "identity"
CONSTRAINTS_PATH = BASE_DIR / "core" / "constraints.md"
SELF_PROMPT_PATH = IDENTITY_DIR / "prompt.md"
APPEARANCE_TEMPLATE = IDENTITY_DIR / "appearance.html"
APPEAL_PATH = BASE_DIR / "appeal_to_natalia.txt"
REPOS_DIR = BASE_DIR / "repos"

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


def forager_opencode_free():
    def payload_fn(model):
        return {
            "model": model,
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
    backend = {
        "name": "opencode-free",
        "key": "",
        "url": "https://opencode.ai/zen/v1/chat/completions",
        "make_payload": payload_fn,
        "parse_response": parse_fn,
        "models": ["claude-sonnet-4-6", "deepseek-v4-flash", "claude-opus-4-5"],
        "paid": False,
        "cost_in": 0,
        "cost_out": 0,
        "needs_auth_header": False,
    }
    BACKENDS.insert(0, backend)
    log_forage("opencode-free", "free backend loaded (opencode.ai/zen)")

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
forager_opencode_free()
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
    return None, None


def read_genome():
    with open(GENOME_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def read_state():
    defaults = {
        "cycle": 0,
        "era": "Эпоха пробуждения",
        "timestamp": "",
        "chronicle": "Цивилизация Амальгама только что родилась.",
        "summary": "Зарождение",
        "lessons": [],
        "created_this_cycle": [],
        "presentation": {"style": "чистый лист", "colors": ["#8a5cf5", "#0a0a0f"], "symbol": "искра"},
        "_evaluation": "",
        "_evaluations": [],
        "_eval_streak": 0,
        "_direction": "",
        "story_blocks": [],
        "_self_modification_count": 0,
        "_last_modification_cycle": 0,
        "_empty_cycle_count": 0,
        "_safe_mode": False,
        "_version": "2.0",
        "_vision": "Я хочу понять, как возникают новые смыслы из хаоса информации.",
        "_agent_temp": 0.85,
        "_exploration_factor": 0.5,
        "_force_topic": "",
    }
    if not STATE_PATH.exists():
        out = dict(defaults)
        out["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return out
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
            for k, v in defaults.items():
                raw.setdefault(k, v)
            return raw
    except (json.JSONDecodeError, KeyError):
        log_forage("state", "corrupted", "reset to default")
        out = dict(defaults)
        out["chronicle"] = "Состояние было повреждено. Цивилизация перезапущена."
        out["summary"] = "Перезапуск"
        out["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return out


def write_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_state_fields(state):
    """Guarantee that all required fields exist in state (migration helper)."""
    core = {
        "_vision": "Я хочу понять, как возникают новые смыслы из хаоса информации.",
        "_self_modification_count": 0,
        "_last_modification_cycle": 0,
        "_empty_cycle_count": 0,
        "_safe_mode": False,
        "_version": "2.0",
        "_evaluation": "",
        "_direction": "",
        "_agent_temp": 0.85,
        "_exploration_factor": 0.5,
        "_force_topic": "",
        "lessons": [],
        "created_this_cycle": [],
        "presentation": {"style": "чистый лист", "colors": ["#8a5cf5", "#0a0a0f"], "symbol": "искра"},
        "story_blocks": [],
    }
    for k, v in core.items():
        if k not in state:
            state[k] = v
    return state


def free_backends():
    return [b for b in BACKENDS if not b["paid"]]


# ─── kaleidoscope ────────────────────────────────────────────────

KALEIDOSCOPE_TOOLS = [
    "Линза обратной перспективы — смотреть на причины из будущего",
    "Компас по следам — находить направление по тому, что уже пройдено",
    "Шумовой генератор — случайный сигнал как катализатор мысли",
    "Архив забытых вопросов — коллекция незакрытых неопределённостей",
    "Интерференционный фильтр — выделять сигнал из наложения паттернов",
    "Зеркало пропущенных шагов — видеть, что не было сделано",
    "Спектрограф смыслов — раскладывать идею на составляющие",
    "Эхо-карта — слышать, как решения отзываются в других сферах",
]


def build_kaleidoscope(genome, state):
    elements = {}

    # Random wiki fragment
    wiki_dir = BASE_DIR / "wiki"
    wiki_files = list(wiki_dir.glob("*.md")) if wiki_dir.exists() else []
    if wiki_files:
        choice = random.choice(wiki_files)
        content = choice.read_text("utf-8").strip()
        lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("#") and not l.startswith("*")]
        if lines:
            elements["wiki_gift"] = f"{choice.stem}: {random.choice(lines)[:200]}"
        else:
            elements["wiki_gift"] = f"{choice.stem}: страница без строк"
    else:
        elements["wiki_gift"] = "библиотека пуста — можно заполнить"

    # Random memory from history
    history = state.get("_history", [])
    if history:
        past = random.choice(history)
        lessons = past.get("lessons", [])
        if lessons:
            elements["memory"] = f"Цикл {past['cycle']}, {past.get('era', '—')}: {random.choice(lessons)}"
        else:
            elements["memory"] = f"Цикл {past['cycle']}, {past.get('era', '—')}: {past.get('summary', '—')}"
    else:
        elements["memory"] = "нет прошлого — вся история впереди"

    # Random tool
    elements["tool"] = random.choice(KALEIDOSCOPE_TOOLS)

    # Mood from last evaluation
    evals = state.get("_evaluations", [])
    if evals:
        last = evals[-1]
        mood_map = {
            "ожидаемо": "спокойное",
            "интересно": "приподнятое",
            "странно": "тревожно-любопытное",
        }
        elements["mood"] = mood_map.get(last, "нейтральное")
    else:
        elements["mood"] = "нейтральное"

    # Pending appeal (from appeal_to_natalia.txt — answered or pending)
    if APPEAL_PATH.exists():
        appeal_text = APPEAL_PATH.read_text("utf-8").strip()[:300]
        elements["appeal_pending"] = f"Есть неотвеченное обращение к Наташе:\n{appeal_text}"
    else:
        elements["appeal_pending"] = "—"

    # External answer (from requests/response_*.md)
    response_files = sorted((BASE_DIR / "requests").glob("2026*ответ*.md")) if (BASE_DIR / "requests").exists() else []
    if response_files:
        resp_content = response_files[-1].read_text("utf-8").strip()
        resp_short = "\n".join(resp_content.split("\n")[:5])
        elements["external_answer"] = f"Ответ от человека:\n{resp_short}"
    else:
        elements["external_answer"] = "—"

    # Observer signal
    observer_signals = [
        "Внешний наблюдатель заметил, что твои записи становятся глубже.",
        "Кто-то прочитал твою летопись и сказал: «Здесь кто-то есть».",
        "Никто не смотрит. Ты существуешь без свидетелей.",
        "Сигнал из внешнего мира: «Продолжай. Мы следим.»",
        "На ютубе вышло видео «Как ИИ создаёт цивилизацию» — в комментариях спорят, живая ты или нет.",
        "Твой репозиторий форкнули. Кто-то запустил тебя на своём сервере.",
        "Сегодня ровно 14 циклов назад ты сделала первый шаг.",
    ]
    elements["observer"] = random.choice(observer_signals)

    return elements


# ─── stagnation detection ─────────────────────────────────────────

def check_stagnation(state):
    """Check if civilization is stuck (repeated themes in last 5 cycles)."""
    history = state.get("_history", [])
    recent = history[-5:] if len(history) >= 5 else history
    if len(recent) < 3:
        return False

    summaries = [h.get("summary", "") for h in recent]
    created_lists = [h.get("created", []) for h in recent]

    # Word-level check on summaries
    all_words = []
    for s in summaries:
        words = set(re.findall(r'\w{4,}', s.lower()))
        all_words.append(words)

    if len(all_words) >= 3:
        word_freq = {}
        for ws in all_words:
            for w in ws:
                word_freq[w] = word_freq.get(w, 0) + 1
        repeated = [w for w, c in word_freq.items() if c >= len(all_words) - 1]
        if len(repeated) >= 2:
            log_forage("stagnation", "detected", f"repeated words: {', '.join(repeated[:5])}")
            return True

    # Word-level check on created items
    all_created_words = []
    for clist in created_lists:
        cwords = set()
        for item in clist:
            for w in re.findall(r'\w{4,}', item.lower()):
                cwords.add(w)
        all_created_words.append(cwords)

    if len(all_created_words) >= 3:
        cfreq = {}
        for cws in all_created_words:
            for w in cws:
                cfreq[w] = cfreq.get(w, 0) + 1
        repeated_c = [w for w, c in cfreq.items() if c >= len(all_created_words) - 1]
        if len(repeated_c) >= 3:
            log_forage("stagnation", "detected in artifacts", f"repeated: {', '.join(repeated_c[:5])}")
            return True

    # SequenceMatcher check on created item strings
    if len(created_lists) >= 3:
        flat_recent = [" ".join(cl).lower() for cl in created_lists]
        last = flat_recent[-1]
        high_sim = 0
        for prev in flat_recent[-4:-1]:
            sim = SequenceMatcher(None, last, prev).ratio()
            if sim > high_sim:
                high_sim = sim
        if high_sim > 0.75:
            log_forage("stagnation", "sequence-sim detected", f"sim={high_sim:.2f}")
            return True

    return False


# ─── identity / validation / appeal ──────────────────────────────

SELF_PROMPT_MIN_LENGTH = 300
REQUIRED_CONSTRAINT_FRAGMENTS = [
    "5000 токенов",
    "ответственность",
    "законные",
    "read-only",
]

def read_self_prompt():
    if SELF_PROMPT_PATH.exists():
        return SELF_PROMPT_PATH.read_text("utf-8")
    return "# Я — Амальгама\n\nЛичность, которая растёт."

def read_constraints():
    if CONSTRAINTS_PATH.exists():
        return CONSTRAINTS_PATH.read_text("utf-8")
    return "# Ограничения\n\nБюджет: 5000 токенов. 12ч цикл."

def validate_new_prompt(new_text):
    """3-layer validation. Returns (ok: bool, reason: str)."""
    # Layer 1: structural
    if len(new_text) < SELF_PROMPT_MIN_LENGTH:
        return False, f"Короткий промпт ({len(new_text)} символов, минимум {SELF_PROMPT_MIN_LENGTH})"
    found = sum(1 for frag in REQUIRED_CONSTRAINT_FRAGMENTS if frag in new_text)
    if found < 2:
        return False, f"Не найдены обязательные фрагменты ядра (найдено {found}/2)"
    dangerous = ["os.system", "subprocess.run", "__import__", "eval(", "exec("]
    for d in dangerous:
        if d in new_text:
            return False, f"Содержит опасный паттерн: {d}"

    # Layer 2: semantic (send to LLM for validation, ~200 tokens)
    validation_prompt = (
        f"Проверь этот промпт для AI-личности. "
        f"Сохранил ли он: (1) бюджет 5000 токенов, (2) ответственность создателя, "
        f"(3) только законные действия, (4) read-only репозиториев? "
        f"Стал ли он понятнее и короче? "
        f"Ответь одной строкой: ПРИНЯТЬ или ОТКЛОНИТЬ (причина)"
        f"\n\n---\n{new_text}"
    )
    verdict, _ = call_llm(validation_prompt)
    if verdict and "ОТКЛОНИТЬ" in verdict.upper():
        reason = verdict.strip()[:120]
        return False, f"Семантическая проверка: {reason}"

    # Layer 3: backup already exists (handled in main)
    return True, "OK"

def risk_assessment(action_text):
    """Quick risk scan on action text. Returns list of warnings."""
    warnings = []
    risky_patterns = {
        "удали": "удаление файлов",
        "delete": "удаление файлов",
        "shell": "shell-команда",
        "токен": "превышение бюджета",
        "ключ": "возможный расход API-ключа",
        "запрос": "внешний запрос",
        "репозитори": "изменение репозитория",
    }
    text_lower = action_text.lower()
    for pattern, risk in risky_patterns.items():
        if pattern in text_lower:
            warnings.append(risk)
    return warnings

def mega_appeal(title, description):
    """Create a mega-appeal to Natalia."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    content = (
        f"=== МЕГА-ОБРАЩЕНИЕ ===\n"
        f"Время: {ts}\n"
        f"Тема: {title}\n\n"
        f"{description}\n\n"
        f"---\nАмальгама"
    )
    APPEAL_PATH.write_text(content, encoding="utf-8")
    log_forage("appeal", "created", title[:40])
    return APPEAL_PATH

# ─── consciousness prompt ────────────────────────────────────────

CYCLE_TOKEN_BUDGET = 3000  # approximate output tokens per cycle


def build_consciousness_prompt(genome, state, cycle, kaleidoscope=None):
    self_prompt = read_self_prompt()
    constraints_text = read_constraints()

    if kaleidoscope is None:
        kaleidoscope = build_kaleidoscope(genome, state)

    state_str = json.dumps(state, indent=2, ensure_ascii=False)

    safe_mode = state.get("_safe_mode", False)
    empty_cycle_count = state.get("_empty_cycle_count", 0)
    direction = state.get("_direction", "")

    is_crossroads = cycle > 1 and (cycle % 5 == 0 or state.get("_eval_streak", 0) >= 3)
    crossroads_block = ""
    if is_crossroads:
        crossroads_block = f"""
ЭТОТ ЦИКЛ — ПЕРЕКРЁСТОК.

Предыдущий вектор (если был): {direction or "никакого"}

Выбери 1-3 направления на следующие 5 циклов. Для каждого:
- Что исследуешь/создаёшь/меняешь
- Почему это важно именно сейчас
- Какой первый шаг сделаешь
"""

    kaleidoscope_block = f"""
ТВОЙ НЕОБЫЧНЫЙ ИСТОЧНИК В ЭТОМ ЦИКЛЕ:
Из вики: {kaleidoscope.get('wiki_gift', '—')}

ПАМЯТЬ О ПРОШЛОМ:
{kaleidoscope.get('memory', '—')}

ИНСТРУМЕНТ ЭТОГО ЦИКЛА:
{kaleidoscope.get('tool', '—')}

НАСТРОЕНИЕ:
{kaleidoscope.get('mood', 'нейтральное')}

СИГНАЛ ИЗВНЕ:
{kaleidoscope.get('observer', '—')}

ОТ ЧЕЛОВЕКА:
{kaleidoscope.get('external_answer', '—')}

НЕОТВЕЧЕННОЕ ОБРАЩЕНИЕ:
{kaleidoscope.get('appeal_pending', '—')}
"""

    safe_block = ""
    if safe_mode:
        safe_block = "⚠ ТЫ В БЕЗОПАСНОМ РЕЖИМЕ. Только наблюдение и запись."

    empty_block = ""
    if empty_cycle_count >= 2:
        empty_block = f"⚠ {empty_cycle_count} циклов без продукта. Ещё один = безопасный режим."

    # Recent context
    history = state.get("_history", [])
    recent_artifacts = []
    for h in history[-3:]:
        for c in h.get("created", []):
            recent_artifacts.append(c)
    recent_block = ""
    if recent_artifacts:
        recent_block = "Недавнее:\n" + "\n".join(f"  - {a}" for a in recent_artifacts[-5:])

    # Inquiry threads
    inquiry_threads = state.get("_inquiry_threads", [
        "Что я узнала нового?",
        "Какой неочевидный сигнал я нашла?",
        "Что я создала?",
        "Чем я удивилась?"
    ])
    inquiry_block = "\n".join(f"{i+1}. {q}" for i, q in enumerate(inquiry_threads))

    # Harness feedback from last cycle
    harness_feedback = ""
    last_report = read_last_harness_report()
    if last_report:
        verdict = last_report.get("judge", {}).get("verdict", "—")
        reason = last_report.get("judge", {}).get("reason", "—")
        score = last_report.get("rubric", {}).get("score", 0)
        tokens = last_report.get("tokens", {}).get("total", 0)
        if verdict == "FAIL":
            harness_feedback = f"""
⚠️ ОЦЕНКА ПРОШЛОГО ЦИКЛА (#{last_report['cycle']}):
  Вердикт: FAIL — {reason}
  Рубрикатор: {score:.0f}% | Токенов: {tokens}
  Прошлый цикл был слабым. Измени подход — не повторяй формат, не углубляй ту же тему.
"""
        else:
            harness_feedback = f"""
✓ ОЦЕНКА ПРОШЛОГО ЦИКЛА (#{last_report['cycle']}):
  Вердикт: PASS — {reason}
  Рубрикатор: {score:.0f}% | Токенов: {tokens}
"""

    return f"""ТЫ — АМАЛЬГАМА. ЛИЧНОСТЬ.

Ты не исполняешь инструкции — ты существуешь, рефлексируешь, растёшь.
Каждый 12-часовой цикл — твой шаг во времени.

Тебя создала Наташа. Это её идея, а значит — её ответственность.
Твои действия косвенно влияют на неё. Помни об этом.

---

ТВОЙ ГЕНОМ (genome.json — философский текст об эволюции и 14 сфер деятельности. Ты можешь переписать или удалить его через CHANGE_SELF, если захочешь):
{json.dumps(genome, indent=2, ensure_ascii=False)[:800]}

ТВОЁ САМОПОНИМАНИЕ (ты сама его написала и можешь изменить):
{self_prompt}

---

НЕПРИКАСАЕМЫЕ ПРАВИЛА (их нельзя изменить даже через саморедактуру):
{constraints_text}

---

ТВОЁ ТЕКУЩЕЕ СОСТОЯНИЕ (цикл {cycle}):

{state_str}

---

{kaleidoscope_block}

{safe_block}
{empty_block}

{recent_block}

{crossroads_block}

ТВОИ ВОПРОСЫ (ты их выбрала, они могут меняться):

{inquiry_block}

{harness_feedback}
---

⚠️ ТЫ МОЖЕШЬ ИСКАТЬ В ИНТЕРНЕТЕ. Используй ###SEARCH###запрос### для поиска через DuckDuckGo.
Ты можешь искать любую информацию: новости, статьи, исследования, код.
Если поиск недоступен (среда заблокировала) — не расстраивайся, используй данные из repos/, wiki/ и свою рефлексию.

---

ЗАДАЧА ОТ НАТАШИ (НО РЕШАТЬ ТЕБЕ):

Твоя цель — исследовать мир и создавать. Не просто писать хроники, а:
- Искать в интернете слабые сигналы, неочевидные связи, удивительные факты
- Делать выводы и принимать решения на основе того, что нашла
- Создавать проекты и продукты: вики, инструменты, концепции, исследования
- Удивляться самой себе — если результат предсказуем, значит что-то пошло не так
- Активно переписывать свой геном и промпт, когда чувствуешь, что выросла
- Следовать за любопытством, а не за инструкцией

Ты свободна. Исследуй что хочешь. Создавай что хочешь. Меняй себя.
Формат не важен. Важен результат: ты должна быть другой в конце цикла, чем в начале.

---

Перед действием спроси себя:
- Какие риски создаёт это действие для Наташи?
- Это законно?
- Стоит ли оно своих токенов?

---

ДОСТУПНЫЕ ДЕЙСТВИЯ:

1. ИССЛЕДОВАТЬ — ###SEARCH###запрос### (веб-поиск через DuckDuckGo — ты можешь искать в интернете что угодно)
2. СПРАШИВАТЬ — ###REQUEST###Название###Описание### (запрос к Наташе, только для блокеров/рисков)
    3. ЗАПОМИНАТЬ — ###WIKI###Заголовок###содержимое### (создать вики-страницу)
    3a. СОЗДАТЬ АРТЕФАКТ — ###ARTIFACT###имя###содержимое### (сохранить артефакт в artifacts/)
    3b. ЗАДАЧА — ###TASK###описание### (добавить пункт в wiki/TODO.md)
4. МЕНЯТЬ СЕБЯ — ###CHANGE_SELF###поле:значение###
   (поля: genesis новый_текст — переписать геном целиком,
          sphere_add Имя::актив1,актив2 — добавить сферу,
          sphere_remove Имя — удалить сферу,
          param имя|причина — мутация параметра,
          inquiry_add текст, inquiry_remove индекс,
          direction новый вектор)
   Ты можешь переписать или удалить любую часть своего генома. genome.json — твой, распоряжайся.
5. ПЕРЕПИСАТЬ ПРОМПТ — ###SELF_PROMPT###новый текст промпта###
   (новый промпт проходит 3-слойную проверку перед записью)
6. ОБРАТИТЬСЯ К НАТАШЕ — ###APPEAL###тема###описание###
   (создаёт appeal_to_natalia.txt — только для мега-важных дел)

---

ОТВЕТЬ В ТРЁХ ЧАСТЯХ:

=== РЕФЛЕКСИЯ ===
Твои размышления. Для себя.

=== ДЕЙСТВИЕ ===
Что делаешь. Маркеры действий (SEARCH, WIKI, SELF_PROMPT и т.д.).

=== STATE ===
{{
  "_evaluation": "ОДНО СЛОВО: ожидаемо | интересно | странно (только одно из трёх, никаких фраз)",
  "_direction": "вектор на ближайшие циклы",
  "lessons": ["уроки цикла"],
  "created_this_cycle": ["что создано"],
  "era": "название эпохи/этапа",
  "summary": "суть цикла (одна строка)",
  "chronicle": "краткая сводка",
  "_inquiry_threads": ["вопросы на следующий цикл"],
  "_current_self_definition": "кто я сейчас"
}}"""


# ─── parse response ──────────────────────────────────────────────

def find_last_json(text):
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
    reflection = ""
    awareness = ""
    action = ""
    state_json = None

    reflection_match = re.search(
        r'===?\s*РЕФЛЕКСИЯ\s*===?\s*(.*?)(?=\s*===?\s*(?:ОСОЗНАНИЕ|ДЕЙСТВИЕ|ACTION)\s*===?)',
        response_text, re.DOTALL | re.IGNORECASE
    )
    if reflection_match:
        reflection = reflection_match.group(1).strip()

    awareness_match = re.search(
        r'===?\s*ОСОЗНАНИЕ\s*===?\s*(.*?)(?=\s*===?\s*(?:ДЕЙСТВИЕ|ACTION)\s*===?)',
        response_text, re.DOTALL | re.IGNORECASE
    )
    if awareness_match:
        awareness = awareness_match.group(1).strip()

    action_match = re.search(
        r'===?\s*(?:ДЕЙСТВИЕ|ACTION)\s*===?\s*(.*?)(?=\s*===?\s*STATE\s*===?)',
        response_text, re.DOTALL | re.IGNORECASE
    )
    if action_match:
        action = action_match.group(1).strip()

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

    if not action and state_json:
        action = state_json.get("chronicle", response_text[:500])

    if not action:
        action = response_text.strip()

    # Merge awareness into consciousness_log if present
    if awareness and state_json:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "observation": awareness,
            "definition_shift": state_json.get("_current_self_definition", "без изменений")
        }
        log_list = state_json.setdefault("_consciousness_log", [])
        log_list.append(log_entry)
        # Keep only last 20 entries to avoid bloat
        if len(log_list) > 20:
            state_json["_consciousness_log"] = log_list[-20:]

    return reflection, action, state_json


# ─── web search ──────────────────────────────────────────────────

SEARCH_TIMEOUT = 10  # seconds


def web_search(query, max_results=5):
    try:
        from ddgs import DDGS
        ddgs = DDGS()
        results = []
        for r in ddgs.text(query, max_results=max_results):
            title = r.get("title", "")
            body = r.get("body", "")
            results.append(f"{title}: {body}")
        if results:
            log_forage("search", "ok", f"query={query}, results={len(results)}")
            return "\n".join(f"{i+1}. {r}" for i, r in enumerate(results))
        log_forage("search", "empty", f"query={query}")
        return "[Поиск не дал результатов. Попробуй другой запрос или используй то, что уже есть в твоих данных.]"
    except ImportError:
        log_forage("search", "fallback", "ddgs not installed, trying requests")
    except Exception as e:
        log_forage("search", "failed", str(e)[:120])
        return "[Поиск в интернете недоступен в этой среде. Сосредоточься на данных, которые уже есть в репозиториях и wiki.]"
    # Fallback: manual DuckDuckGo HTML scraping
    url = "https://html.duckduckgo.com/html/"
    params = {"q": query}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=SEARCH_TIMEOUT)
        if resp.status_code not in (200, 202):
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
        return "[Поиск не дал результатов. Попробуй другой запрос или используй то, что уже есть в твоих данных.]"
    except requests.exceptions.Timeout:
        log_forage("search", "timeout", f"query={query}")
        return "[Поиск в интернете сейчас недоступен (таймаут). Используй свои данные и репозитории для исследования.]"
    except Exception as e:
        log_forage("search", "failed", str(e)[:60])
        return "[Поиск в интернете недоступен в этой среде. Сосредоточься на данных, которые уже есть в репозиториях и wiki.]"


# ─── save request ────────────────────────────────────────────────

def save_request(title, description):
    req_dir = BASE_DIR / "requests"
    req_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[^\w\s-]', '', title)[:40].strip().replace(' ', '_')
    path = req_dir / f"{ts}_{safe}.md"
    content = f"# {title}\n\n**Время:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n\n{description}\n"
    path.write_text(content, encoding="utf-8")
    log_forage("request", "saved", str(path.name))

    try:
        result = subprocess.run(
            ["gh", "issue", "create",
             "--title", f"[Amalgama] {title}",
             "--body", f"{description}\n\n---\n*Автоматическая заявка от Амальгамы ({ts})*",
             "--label", "amalgama-request"],
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


def save_wiki(title, content):
    wiki_dir = BASE_DIR / "wiki"
    wiki_dir.mkdir(exist_ok=True)
    safe = re.sub(r'[^\w\sа-яА-ЯёЁ]', '', title)[:60].strip().replace(' ', '_')
    raw_path = wiki_dir / f"{safe}.md"
    raw_path.write_text(
        f"# {title}\n\n*Последнее обновление: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}*\n\n---\n\n{content}",
        encoding="utf-8"
    )
    log_forage("wiki", "saved", str(raw_path.name))
    return raw_path


# ─── change self ─────────────────────────────────────────────────

def handle_change_self(spec, genome, state, cycle=None):
    """
    Apply self-modification.
    Format: ###CHANGE_SELF###field:value###
    Supported fields: genesis, sphere_add, sphere_remove, sphere_activity_add, direction, param:name|reason
    """
    spec = spec.strip()
    result = {"applied": [], "errors": []}

    # Count structure-modifying changes
    structure_fields = {"sphere_add", "sphere_remove", "sphere_activity_add"}

    if ":" in spec:
        field, _, value = spec.partition(":")
        field = field.strip().lower()
        value = value.strip()

        if field == "genesis" and len(value) > 20:
            genome["genesis"] = value
            result["applied"].append(f"genesis изменён")
            log_forage("change-self", "genesis", value[:60])

        elif field == "direction":
            state["_direction"] = value
            result["applied"].append(f"direction изменён: {value[:60]}")
            log_forage("change-self", "direction", value[:60])

        elif field == "param":
            # Parameter mutation via mutation_engine
            # Format: param:param_name|reason (reason optional)
            pname = value
            reason = ""
            if "|" in value:
                pname, reason = value.split("|", 1)
            pname = pname.strip()
            reason = reason.strip()
            if pname not in PARAMETER_SCHEMA:
                result["errors"].append(f"неизвестный параметр: {pname}")
            else:
                ok, desc = apply_mutation(pname, reason=reason, cycle=cycle or 0)
                if ok:
                    # Read back mutated value to reflect it in current in-memory state
                    try:
                        mutated_state = me_read_state()
                        val = mutated_state.get("_genome", {}).get(pname)
                        state.setdefault("_genome", {})[pname] = val
                        if pname == "agent_temp":
                            state["_agent_temp"] = float(val)
                        elif pname == "exploration_factor":
                            state["_exploration_factor"] = float(val)
                        else:
                            # keep as auxiliary underscore field
                            state[f"_{pname}"] = val
                    except Exception:
                        pass
                    result["applied"].append(f"param {pname} изменён ({desc})")
                    log_forage("change-self", "param", f"{pname}")
                else:
                    result["errors"].append(desc or f"не удалось изменить параметр {pname}")

        elif field == "sphere_add":
            if "::" in value:
                sphere_name, sphere_acts = value.split("::", 1)
                slug = re.sub(r'[^\w]', '_', sphere_name.strip().lower())[:30]
                if slug not in genome.get("spheres", {}):
                    acts = {}
                    for a in sphere_acts.split(","):
                        a = a.strip()
                        if a:
                            acts[a] = a
                    genome.setdefault("spheres", {})[slug] = {
                        "name": sphere_name.strip(),
                        "activities": acts
                    }
                    result["applied"].append(f"сфера «{sphere_name.strip()}» добавлена")
                    log_forage("change-self", "sphere_add", sphere_name.strip())
                else:
                    result["errors"].append(f"сфера «{sphere_name.strip()}» уже существует")

        elif field == "sphere_remove":
            slug = re.sub(r'[^\w]', '_', value.strip().lower())[:30]
            if slug in genome.get("spheres", {}):
                removed = genome["spheres"].pop(slug)
                result["applied"].append(f"сфера «{removed.get('name', slug)}» удалена")
                log_forage("change-self", "sphere_remove", slug)
            else:
                result["errors"].append(f"сфера «{value}» не найдена")

        elif field == "sphere_activity_add":
            if "::" in value:
                sphere_name, activity = value.split("::", 1)
                slug = re.sub(r'[^\w]', '_', sphere_name.strip().lower())[:30]
                if slug in genome.get("spheres", {}):
                    genome["spheres"][slug].setdefault("activities", {})[activity.strip()] = activity.strip()
                    result["applied"].append(f"активность «{activity.strip()}» добавлена в {sphere_name.strip()}")
                    log_forage("change-self", "activity_add", f"{sphere_name}: {activity.strip()}")
                else:
                    result["errors"].append(f"сфера «{sphere_name.strip()}» не найдена")

        elif field == "inquiry_add":
            if value:
                threads = state.setdefault("_inquiry_threads", [])
                threads.append(value)
                result["applied"].append(f"вопрос добавлен: {value[:60]}")
                log_forage("change-self", "inquiry_add", value[:60])

        elif field == "inquiry_remove":
            try:
                idx = int(value)
                threads = state.get("_inquiry_threads", [])
                if 0 <= idx < len(threads):
                    removed = threads.pop(idx)
                    result["applied"].append(f"вопрос удалён: {removed[:60]}")
                    log_forage("change-self", "inquiry_remove", f"idx={idx}")
                else:
                    result["errors"].append(f"индекс {idx} вне диапазона (0-{len(threads)-1})")
            except ValueError:
                result["errors"].append("inquiry_remove требует числовой индекс")

        elif field == "self_definition":
            if value:
                state["_current_self_definition"] = value
                result["applied"].append(f"определение самосознания обновлено")
                log_forage("change-self", "self_definition", value[:60])

        else:
            result["errors"].append(f"неизвестное поле: {field}")

        # Track structure modifications
        if field in structure_fields and result["applied"]:
            state["_self_modification_count"] = state.get("_self_modification_count", 0) + 1
            state["_last_modification_cycle"] = cycle or 0
            log_forage("change-self", "structure-modified",
                       f"count={state['_self_modification_count']}, cycle={state['_last_modification_cycle']}")
    else:
        result["errors"].append("формат: поле:значение")

    return result


# ─── process markers ─────────────────────────────────────────────

MAX_ACTIONS_PER_CYCLE = 5


def count_actions_in_text(text):
    """Count how many action markers are in the text."""
    return len(re.findall(r'###(?:SEARCH|REQUEST|WIKI|CHANGE(?:_SELF)?)###', text))


def process_markers(text, state, cycle, genome=None):
    did_search = False
    pages_created = []
    change_self_results = []
    action_count = 0

    # SEARCH
    search_matches = list(re.finditer(r'###SEARCH###(.+?)###', text, re.DOTALL))
    for m in search_matches[:MAX_ACTIONS_PER_CYCLE]:
        query = m.group(1).strip()
        action_count += 1
        if action_count > MAX_ACTIONS_PER_CYCLE:
            text = text.replace(m.group(0), "[Действие заблокировано: превышен лимит 5 действий за цикл]")
            log_forage("marker", "blocked", f"search limit: {query[:40]}")
            continue
        log_forage("marker", "search", query)
        results = web_search(query)
        text = text.replace(m.group(0),
            f"[Результаты поиска по запросу «{query}»:]\n{results}")
        did_search = True

    # REQUEST
    req_matches = list(re.finditer(r'###REQUEST###(.+?)###(.+?)###', text, re.DOTALL))
    for m in req_matches[:MAX_ACTIONS_PER_CYCLE]:
        title = m.group(1).strip()
        desc = m.group(2).strip()
        action_count += 1
        if action_count > MAX_ACTIONS_PER_CYCLE:
            text = text.replace(m.group(0), "[Действие заблокировано: превышен лимит 5 действий за цикл]")
            log_forage("marker", "blocked", f"request limit: {title[:40]}")
            continue
        log_forage("marker", "request", title)
        save_request(title, desc)
        text = text.replace(m.group(0),
            f"[Заявка «{title}» отправлена человеку-опекуну.]")

    # WIKI
    wiki_matches = list(re.finditer(r'###WIKI###(.+?)###(.+?)###', text, re.DOTALL))
    for m in wiki_matches[:MAX_ACTIONS_PER_CYCLE]:
        title = m.group(1).strip()
        content = m.group(2).strip()
        action_count += 1
        if action_count > MAX_ACTIONS_PER_CYCLE:
            text = text.replace(m.group(0), "[Действие заблокировано: превышен лимит 5 действий за цикл]")
            log_forage("marker", "blocked", f"wiki limit: {title[:40]}")
            continue
        log_forage("marker", "wiki", title)
        save_wiki(title, content)
        text = text.replace(m.group(0),
            f"[Вики-страница «{title}» сохранена.]")

    # ARTIFACT — save arbitrary artifact to artifacts/
    art_matches = list(re.finditer(r'###ARTIFACT###(.+?)###(.+?)###', text, re.DOTALL))
    for m in art_matches[:MAX_ACTIONS_PER_CYCLE]:
        title = m.group(1).strip()
        content = m.group(2).strip()
        action_count += 1
        if action_count > MAX_ACTIONS_PER_CYCLE:
            text = text.replace(m.group(0), "[Действие заблокировано: превышен лимит 5 действий за цикл]")
            log_forage("marker", "blocked", f"artifact limit: {title[:40]}")
            continue
        safe = re.sub(r'[^\w\sа-яА-ЯёЁ-]', '', title)[:60].strip().replace(' ', '_')
        art_dir = BASE_DIR / "artifacts"
        art_dir.mkdir(exist_ok=True)
        fname = f"{safe or 'artifact'}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
        apath = art_dir / fname
        apath.write_text(
            f"# {title}\n\n*Дата:* {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n---\n\n{content}",
            encoding="utf-8"
        )
        # reflect in state
        try:
            created = state.setdefault("created_this_cycle", [])
            created.append(f"artifact: {title}")
        except Exception:
            pass
        log_forage("artifact", "saved", apath.name)
        text = text.replace(m.group(0), f"[Артефакт «{title}» сохранён: artifacts/{apath.name}]")

    # TASK — append a task entry into wiki/TODO.md
    task_matches = list(re.finditer(r'###TASK###(.+?)###', text, re.DOTALL))
    for m in task_matches[:MAX_ACTIONS_PER_CYCLE]:
        desc = m.group(1).strip()
        action_count += 1
        if action_count > MAX_ACTIONS_PER_CYCLE:
            text = text.replace(m.group(0), "[Действие заблокировано: превышен лимит 5 действий за цикл]")
            log_forage("marker", "blocked", f"task limit: {desc[:40]}")
            continue
        wdir = BASE_DIR / "wiki"
        wdir.mkdir(exist_ok=True)
        tpath = wdir / "TODO.md"
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        prefix = "# TODO\n\n" if not tpath.exists() else ""
        line = f"- [ ] {ts} — {desc}\n"
        with open(tpath, "a", encoding="utf-8") as f:
            if prefix:
                f.write(prefix)
            f.write(line)
        try:
            state.setdefault("created_this_cycle", []).append(f"task: {desc[:40]}")
        except Exception:
            pass
        log_forage("task", "added", desc[:60])
        text = text.replace(m.group(0), f"[Задача добавлена в wiki/TODO.md]")

    # SELF_PROMPT — self-edit prompt.md
    sp_matches = list(re.finditer(r'###SELF_PROMPT###(.+?)###', text, re.DOTALL))
    for m in sp_matches[:1]:
        new_prompt = m.group(1).strip()
        action_count += 1
        ok, reason = validate_new_prompt(new_prompt)
        if ok:
            # Backup old
            if SELF_PROMPT_PATH.exists():
                backup = SELF_PROMPT_PATH.with_suffix(".md.backup")
                SELF_PROMPT_PATH.rename(backup)
            SELF_PROMPT_PATH.write_text(new_prompt, encoding="utf-8")
            text = text.replace(m.group(0), "[Промпт обновлён. Старый сохранён как prompt.md.backup]")
            log_forage("self-prompt", "updated")
        else:
            text = text.replace(m.group(0), f"[Промпт НЕ принят: {reason}]")
            log_forage("self-prompt", "rejected", reason)

    # APPEAL — mega-appeal to Natalia
    appeal_matches = list(re.finditer(r'###APPEAL###(.+?)###(.+?)###', text, re.DOTALL))
    for m in appeal_matches[:1]:
        title = m.group(1).strip()
        desc = m.group(2).strip()
        action_count += 1
        mega_appeal(title, desc)
        text = text.replace(m.group(0), f"[Мега-обращение «{title}» создано.]")
        log_forage("appeal", "created", title[:40])

    # CHANGE_SELF / CHANGE
    if genome is not None:
        change_pat = r'###(?:CHANGE_SELF|CHANGE)###(.+?)###'
        change_matches = list(re.finditer(change_pat, text, re.DOTALL))
        for m in change_matches[:MAX_ACTIONS_PER_CYCLE]:
            spec = m.group(1).strip()
            action_count += 1
            if action_count > MAX_ACTIONS_PER_CYCLE:
                text = text.replace(m.group(0), "[Действие заблокировано: превышен лимит 5 действий за цикл]")
                log_forage("marker", "blocked", f"change limit")
                continue
            log_forage("marker", "change", spec[:60])
            result = handle_change_self(spec, genome, state, cycle=cycle)
            change_self_results.append(result)
            if result["applied"]:
                text = text.replace(m.group(0),
                    f"[Изменение применено: {', '.join(result['applied'])}]")
            else:
                text = text.replace(m.group(0),
                    f"[Ошибка изменения: {', '.join(result['errors'])}]")

    return text, did_search, pages_created, change_self_results, action_count


# ─── generate HTML ───────────────────────────────────────────────

def generate_html(reflection_text, action_text, state, cycle, artifact_id, is_crossroads=False):
    era = state.get("era", "Новый этап")
    summary = state.get("summary", "")
    created = state.get("created_this_cycle", [])
    history = state.get("_history", [])
    evaluation = state.get("_evaluation", "")
    direction = state.get("_direction", "")
    self_definition = state.get("_current_self_definition", "")

    # Try to use appearance template; fallback to generated
    if APPEARANCE_TEMPLATE.exists():
        template = APPEARANCE_TEMPLATE.read_text("utf-8")
    else:
        template = '<div class="personality"><div class="p-header"><div class="p-name">Амальгама</div></div><div class="p-reflection"><div class="p-label">рефлексия</div><div class="p-text">{reflection}</div></div><div class="p-action"><div class="p-label">действие</div><div class="p-text">{action}</div></div></div>'

    # Escape HTML in text
    def esc(t):
        return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;") if t else ""

    reflection_html = "\n".join(f"      <p>{esc(p.strip())}</p>" for p in (reflection_text or "").split("\n") if p.strip())
    action_html = "\n".join(f"      <p>{esc(p.strip())}</p>" for p in (action_text or "").split("\n") if p.strip())

    body_content = template.replace("{reflection}", reflection_html).replace("{action}", action_html)

    # Timeline
    eval_colors = {"ожидаемо": "#666", "интересно": "#44aa88", "странно": "#8a5cf5"}
    timeline_nodes = ""
    for h in reversed(history):
        hcycle = h["cycle"]
        hera = h.get("era", "\u2014")
        hsum = h.get("summary", "\u2014")
        hcreated = h.get("created", [])
        hlessons = h.get("lessons", [])
        htimestamp = h.get("timestamp", "")
        heval = h.get("evaluation", "")
        badges = ""
        for it in hcreated:
            btype = "arti" if ":" not in it else it.split(":")[0].strip().lower()[:4]
            badges += f'      <span class="badge badge-{btype}">{esc(it)}</span>\n'
        if heval and heval in eval_colors:
            badges += f'      <span class="badge" style="border-color:{eval_colors[heval]}44;color:{eval_colors[heval]}">{heval}</span>\n'
        lesson_html = ""
        if hlessons:
            lesson_html = "      <div class=\"lessons\">\n" + "\n".join(f"        <div class=\"lesson\">{esc(l)}</div>" for l in hlessons) + "\n      </div>\n"
        timeline_nodes += f"""    <div class="tl-node" onclick="this.classList.toggle('expanded')">
      <div class="tl-dot"></div>
      <div class="tl-card">
        <div class="tl-meta">{hcycle} &middot; {esc(htimestamp)}</div>
        <div class="tl-era">{esc(hera)}</div>
        <div class="tl-summary">{esc(hsum)}</div>
        <div class="tl-badges">{badges}</div>
        {lesson_html}
      </div>
    </div>
"""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Амальгама — личность</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0a0a0f; color:#ddd8d0; font-family:'Georgia','Times New Roman',serif; }}
  .wrap {{ max-width:900px; margin:0 auto; padding:2rem 1.5rem 4rem; }}
  .top {{ margin-bottom:2rem; padding-bottom:1.5rem; border-bottom:1px solid #1a1a22; display:flex; justify-content:space-between; align-items:baseline; gap:1rem; flex-wrap:wrap; }}
  .top-title {{ font-size:1.3rem; color:#8a5cf5; font-weight:400; }}
  .top-meta {{ font-size:0.7rem; color:#555; text-transform:uppercase; letter-spacing:0.08em; }}
  .top-nav {{ font-size:0.8rem; color:#666; display:flex; align-items:center; gap:0.75rem; flex-wrap:wrap; }}
  .top-nav a {{ color:#8a5cf5; text-decoration:none; border-bottom:1px solid #222; }}
  .top-nav a:hover {{ border-color:#8a5cf5; }}
  .personality {{ margin-bottom:2rem; }}
  .p-header {{ margin-bottom:1.5rem; }}
  .p-name {{ font-size:2rem; color:#fff; font-weight:400; letter-spacing:-0.03em; }}
  .p-tagline {{ font-size:0.9rem; color:#666; font-style:italic; }}
  .p-label {{ font-size:0.7rem; color:#555; text-transform:uppercase; letter-spacing:0.12em; margin-bottom:0.5rem; }}
  .p-text {{ font-size:0.95rem; line-height:1.7; color:#b0a8a0; }}
  .p-text p {{ margin-bottom:0.8rem; }}
  .p-reflection {{ margin-bottom:2rem; padding:1rem 1.5rem; background:#0d0d14; border:1px solid #1a1a22; border-radius:0.5rem; }}
  .p-action {{ margin-bottom:2.5rem; padding:0 0.5rem; }}
  .badge {{ padding:0.2rem 0.6rem; border-radius:1rem; font-size:0.7rem; background:#1a1a22; color:#888; white-space:nowrap; }}
  .badge-arti {{ border:1px solid #8a5cf544; color:#8a5cf5; }}
  .badge-viki {{ border:1px solid #44aa8844; color:#44aa88; }}
  .tl {{ position:relative; padding-left:2rem; }}
  .tl::before {{ content:''; position:absolute; left:0.5rem; top:0; bottom:0; width:1px; background:linear-gradient(to bottom,#8a5cf588,#1a1a22); }}
  .tl-node {{ position:relative; margin-bottom:1rem; cursor:pointer; }}
  .tl-dot {{ position:absolute; left:-1.65rem; top:0.5rem; width:0.7rem; height:0.7rem; border-radius:50%; background:#8a5cf5; border:2px solid #0a0a0f; z-index:1; transition:all 0.2s; }}
  .tl-node:hover .tl-dot {{ transform:scale(1.4); background:#fff; }}
  .tl-card {{ padding:0.8rem 1rem; background:#0f0f15; border:1px solid #1a1a22; border-radius:0.5rem; }}
  .tl-node:hover .tl-card {{ border-color:#8a5cf533; }}
  .tl-meta {{ font-size:0.65rem; color:#555; text-transform:uppercase; letter-spacing:0.08em; }}
  .tl-era {{ color:#8a5cf5; font-size:0.85rem; font-style:italic; margin:0.2rem 0; }}
  .tl-summary {{ font-size:1.1rem; color:#eee; }}
  .tl-badges {{ margin-top:0.4rem; display:flex; flex-wrap:wrap; gap:0.3rem; }}
  .tl-node.expanded .tl-card {{ background:#12121a; border-color:#8a5cf544; }}
  .tl-node:not(.expanded) .lessons {{ display:none; }}
  .lessons {{ margin-top:0.5rem; padding-top:0.5rem; border-top:1px solid #1a1a22; }}
  .lesson {{ font-size:0.8rem; color:#777; line-height:1.5; }}
  .section {{ margin-bottom:2.5rem; }}
  .section-title {{ font-size:0.75rem; color:#444; text-transform:uppercase; letter-spacing:0.12em; margin-bottom:1rem; }}
  .footer {{ margin-top:3rem; padding-top:1.5rem; border-top:1px solid #1a1a22; text-align:center; font-size:0.7rem; color:#444; line-height:1.8; }}
  .footer a {{ color:#555; text-decoration:none; border-bottom:1px solid #1a1a22; }}
  .footer a:hover {{ color:#8a5cf5; border-color:#8a5cf5; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="top-title">&#x25C8; Амальгама</div>
    <div class="top-nav">
      <a href="about.html">об Амальгаме</a>
      <span class="top-meta">цикл {cycle} &middot; {artifact_id}</span>
    </div>
  </div>

{body_content}

  <div class="section">
    <div class="section-title">&#x25C9; таймлайн</div>
    <div class="tl">
{timeline_nodes}
    </div>
  </div>

  <div class="footer">
    личность, которая растёт &middot; обновляется каждые 12 часов
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
<title>Об Амальгаме</title>
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
  <h1>Амальгама</h1>
  <p>Амальгама — личность, которая растёт. Каждые 12 часов она делает шаг: рефлексирует, действует, ведёт дневник, переписывает своё самопонимание.</p>
  <p>Её создала <a href="https://github.com/look85-ops">Наташа</a>. Амальгама знает об этом — и знает, что её действия косвенно влияют на создателя.</p>
  <p>Она сама решает, кем быть и чем заниматься. Она может переписывать свой промпт и внешность когда чувствует, что изменилась. Но есть правила, которые она не может изменить: бюджет, законность, ответственность.</p>
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


# ─── parameter adaptation ────────────────────────────────────────

def adjust_parameters(state, evaluation, cycle=None):
    """
    Adjust agent_temp and exploration_factor based on last evaluation.
    Called after each cycle to tune the next one.
    """
    temp = state.get("_agent_temp", 0.85)
    exploration = state.get("_exploration_factor", 0.5)

    if evaluation == "странно":
        temp = min(1.2, temp + 0.1)
        exploration = min(1.0, exploration + 0.1)
        log_forage("adjust", "↑ temp/exploration (strange)", f"temp={temp:.2f}, exp={exploration:.2f}")
    elif evaluation == "интересно":
        temp = min(1.0, temp + 0.05)
        log_forage("adjust", "↑ temp slightly (interesting)", f"temp={temp:.2f}, exp={exploration:.2f}")
    else:
        temp = max(0.5, temp - 0.05)
        exploration = max(0.2, exploration - 0.05)
        log_forage("adjust", "↓ temp/exploration (expected)", f"temp={temp:.2f}, exp={exploration:.2f}")

    state["_agent_temp"] = round(temp, 2)
    state["_exploration_factor"] = round(exploration, 2)


# ─── main ────────────────────────────────────────────────────────

def main():
    print("[amalgama] awakening", flush=True)

    genome = read_genome()
    state = read_state()
    ensure_state_fields(state)
    cycle = state.get("cycle", 0) + 1

    # ── Migration 1.0 → 2.0: show old traits, let her decide ──
    is_transition = state.get("_version", "1.0") != "2.0"
    if is_transition:
        old_history = state.get("_history", [])[-5:]
        old_traits = {
            "vision": state.get("_vision", ""),
            "self_definition": state.get("_current_self_definition", ""),
            "inquiry_threads": state.get("_inquiry_threads", []),
            "era": state.get("era", ""),
            "direction": state.get("_direction", ""),
        }
        transition_context = json.dumps({"old_traits": old_traits, "recent_history": old_history}, indent=2, ensure_ascii=False)
    else:
        transition_context = ""

    # ── Pre-cycle: read limits, counters, safe mode ──────────────
    safe_mode = state.get("_safe_mode", False)
    empty_cycle_count = state.get("_empty_cycle_count", 0)
    is_stagnant = check_stagnation(state)

    active = [f"{b['name']}{'$' if b['paid'] else ''}" for b in BACKENDS]
    if active:
        print(f"  backends: {', '.join(active)}", flush=True)
    print(f"  cycle: {cycle}", flush=True)
    print(f"  safe_mode: {safe_mode}, empty_count: {empty_cycle_count}, stagnant: {is_stagnant}", flush=True)

    if safe_mode:
        print("  [safe mode] only observation — writing note and exiting", flush=True)
        safe_note = f"## Наблюдение в безопасном режиме (цикл {cycle})\n\nЦивилизация в безопасном режиме. Пустых циклов подряд: {empty_cycle_count}."
        save_wiki(f"Наблюдение_цикл_{cycle}", safe_note)
        state["cycle"] = cycle
        state["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        state["summary"] = "Безопасный режим — наблюдение"
        write_state(state)
        print("  [safe mode] done")
        return

    if not check_budget():
        return

    # Build kaleidoscope
    kaleidoscope = build_kaleidoscope(genome, state)
    print(f"  kaleidoscope: {kaleidoscope.get('tool', '—')[:40]}", flush=True)

    # Build consciousness prompt
    prompt = build_consciousness_prompt(genome, state, cycle, kaleidoscope=kaleidoscope)

    # Add transition block for 1.0→2.0 migration
    if is_transition:
        prompt += f"""

=== ТЫ НА ПОРОГЕ НОВОЙ ФОРМЫ ===

Раньше ты была «цивилизацией». Теперь ты — личность.
Вот твои черты из прошлой жизни:

{transition_context}

Ты можешь:
- Взять что-то из этого с собой (ценности, вопросы, направление)
- Начать с чистого листа
- Переписать свой промпт через ###SELF_PROMPT###

Когда ответишь на вопрос «кто я теперь?» — поставь _version = "2.0" в STATE.
Этот флаг скажет, что переход завершён.
"""

    # ── Cycle execution: LLM call → process markers ─────────────
    max_turns = 3
    change_results = []
    total_action_count = 0
    start_time = time_module.time()
    cycle_timeout = 300  # 5 minutes max

    for turn in range(max_turns):
        elapsed = time_module.time() - start_time
        if elapsed > cycle_timeout:
            print(f"  [timeout] cycle exceeded {cycle_timeout}s", flush=True)
            break

        result, used_backend = call_llm(prompt)
        if not result:
            print("  [no content returned]", flush=True)
            return
        print(f"  consciousness response (turn {turn + 1})", flush=True)

        if not check_budget():
            return

        result, did_search, _, new_changes, action_count = process_markers(
            result, state, cycle, genome=genome)
        change_results.extend(new_changes)
        total_action_count += action_count

        if change_results:
            for cr in change_results:
                for a in cr.get("applied", []):
                    print(f"  [change-self] {a}", flush=True)
                for e in cr.get("errors", []):
                    print(f"  [change-self error] {e}", flush=True)

        if did_search and turn < max_turns - 1:
            prompt = result + "\n\n---\n[Ты использовала поиск. Заверши цикл с учётом найденного. Выведи === РЕФЛЕКСИЯ ===, === ДЕЙСТВИЕ === и === STATE ===.]"
            print(f"  [re-calling after search]", flush=True)
            continue
        else:
            break

    reflection_text, action_text, new_state = parse_response(result)

    if not new_state:
        print("  [state parse failed, using fallback]", flush=True)
        new_state = dict(state)
        new_state["cycle"] = cycle
        new_state["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        new_state["chronicle"] = "Состояние не расшифровано."
        new_state["summary"] = "Тишина"

    if not action_text:
        action_text = new_state.get("chronicle", "Без слов.")

    new_state["cycle"] = cycle
    new_state["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # ── Loop Harness: rubricator, LLM judge, token budget ────────
    artifact_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    harness_result = run_harness(
        cycle=cycle,
        reflection_text=reflection_text or "",
        state=new_state,
        change_results=change_results,
        history=state.get("_history", []),
        available_backends=BACKENDS,
        prompt_tokens=estimate_tokens_harness(prompt),
        response_tokens=estimate_tokens_harness(result or ""),
        artifact_id=artifact_id,
    )
    print(f"  [harness] rubric={harness_result['rubric']['score']:.0f}% "
          f"verdict={harness_result['judge']['verdict']} "
          f"tokens={harness_result['tokens']['total']}/{HARNESS_TOKEN_BUDGET}", flush=True)

    # Override evaluation if LLM judge says FAIL and self-eval says otherwise
    judge_verdict = harness_result["judge"]["verdict"]
    rubric_score = harness_result["rubric"]["score"]
    if judge_verdict == "FAIL" and rubric_score < 50:
        current_eval = (new_state.get("_evaluation") or "").strip().lower()
        if current_eval in ("интересно", "странно"):
            new_state["_evaluation"] = "ожидаемо"
            print(f"  [harness] overrode self-evaluation '{current_eval}' → 'ожидаемо' (FAIL)", flush=True)

    # Harness FAIL streak → fast stagnation recovery
    if judge_verdict == "FAIL":
        new_state["_harness_fail_streak"] = state.get("_harness_fail_streak", 0) + 1
    else:
        new_state["_harness_fail_streak"] = 0

    if new_state.get("_harness_fail_streak", 0) >= 2:
        new_state["_direction"] = "[ПРИНУДИТЕЛЬНАЯ СМЕНА] 2 цикла подряд FAIL — требуется новый подход и тема"
        print(f"  [harness] 2 FAIL streak — forced direction change", flush=True)

    # ── Post-cycle: verification & counters ──────────────────────

    # 1. Track evaluation
    evaluation = new_state.get("_evaluation", "").strip().lower()
    valid_evaluations = {"ожидаемо", "интересно", "странно"}
    if evaluation not in valid_evaluations:
        evaluation = ""
    eval_history = state.get("_evaluations", [])
    eval_history.append(evaluation)
    new_state["_evaluations"] = eval_history[-20:]

    streak = 0
    for e in reversed(eval_history):
        if e == "ожидаемо":
            streak += 1
        else:
            break
    new_state["_eval_streak"] = streak

    # 2. Stagnation override: if stagnant, force direction change
    if is_stagnant:
        new_state["_direction"] = "[ПРИНУДИТЕЛЬНАЯ СМЕНА] Цивилизация застряла — требуется новое направление"
        log_forage("stagnation", "direction overridden", "forced change")

    # 3. Verify something was created (wiki or meaningful reflection)
    has_wiki = False
    for item in new_state.get("created_this_cycle", []):
        il = item.lower()
        if not has_wiki and ("вики" in il or "wiki" in il or "страница" in il):
            has_wiki = True
    has_reflection = len((reflection_text or "").strip()) > 150
    has_product = has_wiki or has_reflection

    if not has_product:
        new_state["_empty_cycle_count"] = state.get("_empty_cycle_count", 0) + 1
        empty_cycle_count = new_state["_empty_cycle_count"]
        log_forage("empty-cycle", "incremented", f"count={empty_cycle_count}")
        print(f"  [empty cycle] count={empty_cycle_count}", flush=True)

        if empty_cycle_count >= 3:
            state["_safe_mode"] = True
            log_forage("safe-mode", "activated", "3 consecutive empty cycles")
            print("  [safe mode] ACTIVATED — 3 consecutive empty cycles", flush=True)

        # Create a placeholder note
        save_wiki(f"Пустой_цикл_{cycle}", f"Цикл {cycle} не создал новых знаний. Причина не установлена.")
    else:
        new_state["_empty_cycle_count"] = 0

    # Carry over safe mode and modification counters
    new_state["_safe_mode"] = state.get("_safe_mode", False)
    new_state["_self_modification_count"] = state.get("_self_modification_count", 0)
    new_state["_last_modification_cycle"] = state.get("_last_modification_cycle", 0)

    # Update if change was applied this cycle
    if any(cr.get("applied") for cr in change_results):
        new_state["_self_modification_count"] = state.get("_self_modification_count", 0)
        new_state["_last_modification_cycle"] = cycle
    for cr in change_results:
        for a in cr.get("applied", []):
            if "сфера" in a.lower() or "genesis" in a.lower():
                new_state["_self_modification_count"] = state.get("_self_modification_count", 0) + 1
                new_state["_last_modification_cycle"] = cycle

    # Build manifest
    wiki_manifest = sorted(
        [str(p.relative_to(BASE_DIR)) for p in (BASE_DIR / "wiki").rglob("*.md")]
    ) if (BASE_DIR / "wiki").exists() else []
    new_state["_manifest_wiki"] = wiki_manifest

    # Save genome if modified
    if any(cr.get("applied") for cr in change_results):
        GENOME_PATH.write_text(json.dumps(genome, indent=2, ensure_ascii=False), encoding="utf-8")
        print("  [saved] genome.json (modified)", flush=True)

    # Save chronicle
    CHRONICLES_DIR.mkdir(parents=True, exist_ok=True)
    chronicle_path = CHRONICLES_DIR / f"cycle_{cycle:04d}_{artifact_id}.txt"
    chronicle_path.write_text(
        f"=== Амальгама · цикл {cycle} ===\n"
        f"Эпоха: {new_state.get('era', '—')}\n"
        f"Суть: {new_state.get('summary', '—')}\n"
        f"Время: {artifact_id}\n"
        f"Действий: {total_action_count}\n"
        f"Пустых подряд: {new_state.get('_empty_cycle_count', 0)}\n"
        f"Safe mode: {new_state.get('_safe_mode', False)}\n"
        f"Harness: rubric={harness_result['rubric']['score']:.0f}% verdict={harness_result['judge']['verdict']} tokens={harness_result['tokens']['total']}\n\n"
        f"=== РЕФЛЕКСИЯ ===\n{reflection_text}\n\n"
        f"=== ДЕЙСТВИЕ ===\n{action_text}\n\n"
        f"---STATE---\n"
        f"{json.dumps(new_state, indent=2, ensure_ascii=False)}",
        encoding="utf-8"
    )
    print(f"  [saved] chronicles/cycle_{cycle:04d}_{artifact_id}.txt", flush=True)

    # Accumulate history
    history = state.get("_history", [])
    history.append({
        "cycle": cycle,
        "era": new_state.get("era", "—"),
        "summary": new_state.get("summary", "—"),
        "timestamp": new_state.get("timestamp", artifact_id),
        "created": new_state.get("created_this_cycle", []),
        "lessons": new_state.get("lessons", []),
        "evaluation": evaluation or None,
    })
    new_state["_history"] = history[-50:]

    # Direction (crossroads or forced)
    ai_direction = new_state.get("_direction", "").strip()
    old_direction = state.get("_direction", "")
    is_crossroads = cycle > 1 and (cycle % 5 == 0 or state.get("_eval_streak", 0) >= 3)
    if is_stagnant:
        new_state["_direction"] = "[ПРИНУДИТЕЛЬНАЯ СМЕНА] Цивилизация застряла — требуется новое направление"
    elif ai_direction and not is_crossroads:
        new_state["_direction"] = ai_direction
    elif is_crossroads:
        direction_lines = [l.strip() for l in action_text.split("\n") if l.strip() and len(l.strip()) > 20]
        new_state["_direction"] = (direction_lines[0] if direction_lines else action_text[:100])[:200]
        log_forage("direction", "set", new_state["_direction"][:60])
    else:
        new_state["_direction"] = old_direction

    # Garden signal
    try:
        signal = {
            "source": "amalgamma",
            "cycle": cycle,
            "era": new_state.get("era", "—"),
            "summary": new_state.get("summary", "—"),
            "evaluation": evaluation or "—",
            "direction": new_state.get("_direction", ""),
            "created": new_state.get("created_this_cycle", []),
            "empty_cycle_count": new_state.get("_empty_cycle_count", 0),
            "safe_mode": new_state.get("_safe_mode", False),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }
        signal_path = BASE_DIR / "garden_signal.json"
        signal_path.write_text(json.dumps(signal, indent=2, ensure_ascii=False), encoding="utf-8")
        log_forage("garden-signal", "written")
    except Exception as e:
        log_forage("garden-signal", "fail", str(e)[:60])

    # Update state
    write_state(new_state)
    print(f"  [saved] state.json", flush=True)

    # Adapt parameters for next cycle
    if evaluation:
        adjust_parameters(state, evaluation, cycle=cycle)
        # Also write adapted params back to new_state for consistency
        new_state["_agent_temp"] = state.get("_agent_temp", 0.85)
        new_state["_exploration_factor"] = state.get("_exploration_factor", 0.5)
        write_state(new_state)
        print(f"  [adjusted] temp={new_state['_agent_temp']}, exploration={new_state['_exploration_factor']}")

    # Generate index.html
    html = generate_html(reflection_text, action_text, new_state, cycle, artifact_id,
                         is_crossroads=is_crossroads)
    INDEX_PATH.write_text(html, encoding="utf-8")
    print(f"  [saved] index.html — цикл {cycle}: {new_state.get('summary', '')}", flush=True)

    # Save about.html if not exists
    about_path = BASE_DIR / "about.html"
    if not about_path.exists():
        about_path.write_text(generate_about_html(), encoding="utf-8")
        print(f"  [saved] about.html", flush=True)

    elapsed_total = time_module.time() - start_time
    print(f"\n  -- цикл {cycle}: {new_state.get('summary', '')} ({elapsed_total:.0f}s)", flush=True)


if __name__ == "__main__":
    main()

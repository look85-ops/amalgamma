import json
import re
from pathlib import Path
from difflib import SequenceMatcher
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent.parent
HARNESS_DIR = BASE_DIR / "harness_reports"
TOKEN_LOG_PATH = BASE_DIR / "token_usage.log"

# ─── Rubricator ───────────────────────────────────────────────────

RUBRIC_CRITERIA = [
    {"id": "artifact_exists",   "name": "Артефакт существует",   "weight": 1.0},
    {"id": "reflection_depth",  "name": "Рефлексия глубокая",    "weight": 1.0},
    {"id": "state_valid",       "name": "JSON state корректен",  "weight": 1.0},
    {"id": "novelty",           "name": "Новизна",               "weight": 1.2},
    {"id": "direction_set",     "name": "Направление задано",    "weight": 0.8},
]

REQUIRED_STATE_FIELDS = [
    "_evaluation", "lessons", "created_this_cycle", "era", "summary", "chronicle",
]


def check_artifact_exists(state, change_results):
    created = state.get("created_this_cycle", [])
    if created and any(len(c) > 20 for c in created):
        return True, f"создано {len(created)} артефактов"
    lessons = state.get("lessons", [])
    if lessons and any(len(l) > 30 for l in lessons):
        return True, f"{len(lessons)} уроков записано"
    if change_results and any(cr.get("applied") for cr in change_results):
        return True, "произведены изменения генома"
    return False, "нет созданных артефактов"


def check_reflection_depth(reflection_text):
    if reflection_text and len(reflection_text.strip()) > 150:
        return True, f"рефлексия {len(reflection_text)} символов"
    return False, f"рефлексия слишком коротка ({len(reflection_text or '')} символов)"


def check_state_valid(state):
    missing = [f for f in REQUIRED_STATE_FIELDS if f not in state]
    if not missing:
        return True, "все обязательные поля присутствуют"
    return False, f"отсутствуют поля: {', '.join(missing)}"


def check_novelty(state, history):
    created = state.get("created_this_cycle", [])
    if not created:
        return False, "нет созданного для сравнения"
    flat_current = " ".join(created).lower()
    recent = history[-3:] if len(history) >= 3 else history
    for h in recent:
        hcreated = h.get("created", [])
        if hcreated:
            flat_prev = " ".join(hcreated).lower()
            sim = SequenceMatcher(None, flat_current, flat_prev).ratio()
            if sim > 0.7:
                return False, f"слишком похоже на цикл {h['cycle']} (sim={sim:.2f})"
    return True, "достаточная новизна"


def check_direction_set(state):
    direction = state.get("_direction", "").strip()
    if not direction:
        return False, "направление не задано"
    if "застряла" in direction or "требуется новое" in direction:
        return False, "направление — заглушка (stagnation)"
    if len(direction) < 20:
        return False, f"направление слишком короткое ({len(direction)} символов)"
    return True, f"направление задано: {direction[:60]}"


def run_rubricator(reflection_text, state, change_results, history):
    checks = [
        ("artifact_exists", "Артефакт существует", check_artifact_exists(state, change_results)),
        ("reflection_depth", "Рефлексия глубокая", check_reflection_depth(reflection_text)),
        ("state_valid", "JSON state корректен", check_state_valid(state)),
        ("novelty", "Новизна", check_novelty(state, history)),
        ("direction_set", "Направление задано", check_direction_set(state)),
    ]
    results = []
    total_weight = 0
    passed_weight = 0
    for cid, cname, (passed, detail) in checks:
        weight = next((cr["weight"] for cr in RUBRIC_CRITERIA if cr["id"] == cid), 1.0)
        total_weight += weight
        if passed:
            passed_weight += weight
        results.append({"id": cid, "name": cname, "passed": passed, "detail": detail, "weight": weight})
    score = (passed_weight / total_weight * 100) if total_weight > 0 else 0
    return results, score


# ─── LLM Judge ────────────────────────────────────────────────────

JUDGE_FEW_SHOT = """
Пример 1 — PASS:
Артефакт: Создана вики-страница «Диагностика культурного артефакта» с пошаговым шаблоном
Рефлексия: 320 символов о методологии безопасной мутации
Direction: Исследовать применимость шаблона на реальных организациях
Вердикт: PASS — создан практический инструмент, есть вектор развития

Пример 2 — FAIL:
Артефакт: не создано
Рефлексия: 45 символов
Direction: требуется новое направление
Вердикт: FAIL — пустой цикл, нет продукта, нет развития

Пример 3 — PASS:
Артефакт: изменён genome.json, раздел genesis
Рефлексия: 210 символов о переосмыслении целей
Direction: Завершить гармонизацию параметров фенотипа
Вердикт: PASS — содержательное изменение себя, есть направление

Пример 4 — FAIL:
Артефакт: создано: ["Продолжение исследования"]
Рефлексия: 80 символов
Direction: та же, что и в прошлом цикле
Вердикт: FAIL — нет конкретики, рефлексия поверхностна
"""


def build_judge_prompt(cycle, reflection_text, state, rubric_results, score):
    created = state.get("created_this_cycle", [])
    direction = state.get("_direction", "")
    lessons = state.get("lessons", [])
    rubric_summary = "\n".join(
        f"  {'✓' if r['passed'] else '✗'} {r['name']}: {r['detail']}"
        for r in rubric_results
    )
    return f"""Ты — строгий судья качества цикла Амальгамы.

Оцени, заслуживает ли этот цикл PASS или FAIL.
Оценивай жёстко: PASS = цикл создал что-то новое И продвинул развитие.
FAIL = пустой цикл, поверхностная рефлексия, отсутствие артефактов.

{JUDGE_FEW_SHOT}

ДАННЫЕ ЦИКЛА {cycle}:

Артефакты цикла: {json.dumps(created, ensure_ascii=False)}
Уроки: {json.dumps(lessons, ensure_ascii=False)}
Направление: {direction}
Рефлексия: {(reflection_text or '')[:500]}

РУБРИКАТОР (весовой): суммарный score = {score:.0f}%
{rubric_summary}

ОТВЕТЬ ОДНОЙ СТРОКОЙ:
PASS (причина) или FAIL (причина)

Только PASS или FAIL. Никаких maybe, borderline, partial."""


def call_llm_judge(prompt, available_backends):
    for backend in available_backends:
        if backend.get("paid"):
            continue
        try:
            import requests
            headers = {}
            if backend["needs_auth_header"]:
                headers["Authorization"] = f"Bearer {backend['key']}"
            for model in backend["models"]:
                payload = backend["make_payload"](model)
                for msg in payload.get("messages", []):
                    if isinstance(msg.get("content"), str):
                        msg["content"] = msg["content"].replace("__PROMPT__", prompt)
                resp = requests.post(backend["url"], headers=headers, json=payload, timeout=60)
                if resp.status_code >= 400:
                    continue
                data = resp.json()
                content = backend["parse_response"](data)
                content = content[0] if isinstance(content, tuple) else content
                if content and len(content) > 10:
                    content = content.strip()
                    if content.upper().startswith("PASS"):
                        return "PASS", content[5:].strip().strip("()") or "цикл продуктивен"
                    elif content.upper().startswith("FAIL"):
                        return "FAIL", content[5:].strip().strip("()") or "цикл не создал ценности"
                    if "PASS" in content.upper():
                        return "PASS", "судья не дал чёткого вердикта, но склоняется к PASS"
                    return "FAIL", "судья не дал чёткого вердикта, вердикт по рубрикатору"
        except Exception:
            continue
    return None, "LLM-судья недоступен"


# ─── Token Budget ─────────────────────────────────────────────────

CYCLE_TOKEN_BUDGET = 5000


def estimate_tokens(text):
    return max(1, int(len(text) / 1.5))


def track_token_usage(cycle, prompt_tokens, response_tokens, artifact_id):
    total = prompt_tokens + response_tokens
    entry = {
        "cycle": cycle,
        "prompt_tokens": prompt_tokens,
        "response_tokens": response_tokens,
        "total": total,
        "budget": CYCLE_TOKEN_BUDGET,
        "within_budget": total <= CYCLE_TOKEN_BUDGET,
        "artifact_id": artifact_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(TOKEN_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


# ─── Harness ──────────────────────────────────────────────────────


def run(cycle, reflection_text, state, change_results, history,
        available_backends, prompt_tokens=0, response_tokens=0, artifact_id=""):
    HARNESS_DIR.mkdir(exist_ok=True)

    rubric_results, rubric_score = run_rubricator(reflection_text, state, change_results, history)

    judge_prompt = build_judge_prompt(cycle, reflection_text, state, rubric_results, rubric_score)
    judge_verdict, judge_reason = call_llm_judge(judge_prompt, available_backends)

    if judge_verdict is None:
        final_verdict = "PASS" if rubric_score >= 60 else "FAIL"
        final_reason = f"Рубрикатор: {rubric_score:.0f}%"
    else:
        final_verdict = judge_verdict
        final_reason = judge_reason

    token_info = track_token_usage(cycle, prompt_tokens, response_tokens, artifact_id)

    report = {
        "cycle": cycle,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "artifact_id": artifact_id,
        "rubric": {"score": round(rubric_score, 1), "criteria": rubric_results},
        "judge": {"verdict": final_verdict, "reason": final_reason, "llm_available": judge_verdict is not None},
        "tokens": token_info,
    }

    report_path = HARNESS_DIR / f"harness_cycle_{cycle:04d}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def read_last_harness_report():
    if not HARNESS_DIR.exists():
        return None
    reports = list(HARNESS_DIR.glob("harness_cycle_*.json"))
    if not reports:
        return None
    def get_cycle_num(path):
        stem = path.stem
        num_str = stem.split("_")[-1]
        return int(num_str)
    latest = max(reports, key=get_cycle_num)
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return None

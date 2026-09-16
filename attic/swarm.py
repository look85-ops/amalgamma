"""Роевая сборка артефакта: Продюсер → Критик → Интегратор.

Каждая роль — отдельный вызов бесплатного бэкенда.
Использует тот же call_llm, что и основной цикл (инъекция через параметр).
"""

# Рубашка этапа — короткое описание роли для промпта.
STAGE_INTRO = {
    "producer": (
        "Ты — ПРОДЮСЕР. Создаёшь первый черновик сложного артефакта. "
        "Дай полную содержательную версию: без пустых общих фраз, с конкретикой, "
        "структурой и примером. Это черновик — он будет доработан командой."
    ),
    "critic": (
        "Ты — СТРОГИЙ КРИТИК. Изучаешь черновик и находишь его слабые места: "
        "нелогичности, общие фразы, отсутствие связи, слишком поверхностные части. "
        "Выдай ровно 3–5 конкретных замечаний, каждому — что именно исправить и как. "
        "Не хвали, только слабые места и правки."
    ),
    "integrator": (
        "Ты — ИНТЕГРАТОР. У тебя есть черновик и замечания критика. "
        "Собери финальную версию артефакта: учти все правки, сохрани сильные части, "
        "доведи до цельного законченного текста. Выдай ТОЛЬКО финальный текст — "
        "без объяснений и списка изменений."
    ),
}


def run_swarm(call_llm, topic, details="", max_stage_tokens_hint=None):
    """Запускает трёхролевой конвейер.

    Возвращает (final, draft, critique) или (None, None, None) при сбое.
    call_llm(prompt) -> (text, backend) | (None, None)
    """
    def stage(key, prompt):
        text, backend = call_llm(prompt)
        if not text:
            return None
        return text.strip()

    base = f"Тема артефакта: {topic}"
    if details:
        base += f"\nДополнительные пожелания: {details}"

    # 1. Продюсер
    producer_prompt = (
        f"{STAGE_INTRO['producer']}\n\n{base}\n\n"
        f"Напиши черновик артефакта. Объём — развёрнутый, по существу."
    )
    draft = stage("producer", producer_prompt)
    if not draft:
        return (None, None, None)

    # 2. Критик
    critic_prompt = (
        f"{STAGE_INTRO['critic']}\n\nЧЕРНОВИК:\n{draft}\n\n"
        f"Дай замечания. Формат: по одному пункту на строку, каждый — «проблема → как исправить»."
    )
    critique = stage("critic", critic_prompt)
    if not critique:
        return (None, None, None)

    # 3. Интегратор
    integrator_prompt = (
        f"{STAGE_INTRO['integrator']}\n\nЧЕРНОВИК:\n{draft}\n\n"
        f"ЗАМЕЧАНИЯ КРИТИКА:\n{critique}\n\n"
        f"Собери финальную версию по теме «{topic}»."
    )
    final = stage("integrator", integrator_prompt)
    if not final:
        return (None, None, None)

    return (final, draft, critique)
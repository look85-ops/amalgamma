"""Schema-based mutation engine for safe self-modification."""

import json
import os
import random
from copy import deepcopy

GENOME_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "genome.json")
STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state.json")


PARAMETER_SCHEMA = {
    "exploration_factor": {"type": float, "min": 0.1, "max": 2.0, "step": 0.1},
    "agent_temp": {"type": float, "min": 0.2, "max": 1.5, "step": 0.1},
    "surprise_threshold": {"type": float, "min": 0.3, "max": 0.95, "step": 0.05},
    "diversity_factor": {"type": float, "min": 0.1, "max": 1.0, "step": 0.05},
}

DESCRIPTION_MAX_LENGTH = 500


def read_genome():
    if not os.path.exists(GENOME_PATH):
        return {}
    with open(GENOME_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def read_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def write_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def ensure_mutation_fields(state):
    if "_mutation_history" not in state:
        state["_mutation_history"] = []
    if "_genome" not in state:
        state["_genome"] = {}
    if "_last_mutation_cycle" not in state:
        state["_last_mutation_cycle"] = 0
    if "_mutation_count" not in state:
        state["_mutation_count"] = 0
    return state


def propose_mutation(current_value, schema_entry):
    """Propose a mutated value within schema bounds."""
    current = float(current_value)
    step = schema_entry["step"]
    delta = random.choice([-step, step, -step * 2, step * 2])
    new_val = round(current + delta, 2)
    new_val = max(schema_entry["min"], min(schema_entry["max"], new_val))
    return new_val


def apply_mutation(param_name, reason="", cycle=0):
    """Apply a single mutation to a parameter. Returns (success, change_desc)."""
    if param_name not in PARAMETER_SCHEMA:
        return False, f"Unknown parameter: {param_name}"

    state = read_state()
    ensure_mutation_fields(state)

    genome = state.get("_genome", {})
    old_val = genome.get(param_name, PARAMETER_SCHEMA[param_name]["min"])

    schema = PARAMETER_SCHEMA[param_name]
    new_val = propose_mutation(old_val, schema)

    genome[param_name] = new_val
    state["_genome"] = genome
    state["_mutation_count"] = state.get("_mutation_count", 0) + 1
    state["_last_mutation_cycle"] = cycle

    change = {
        "cycle": cycle,
        "param": param_name,
        "old": old_val,
        "new": new_val,
        "reason": reason[:DESCRIPTION_MAX_LENGTH],
    }
    state.setdefault("_mutation_history", []).append(change)

    write_state(state)
    return True, f"{param_name}: {old_val} -> {new_val} ({reason})"


def mutate_description(description, reason=""):
    """Safely mutate the description/genesis string (append or modify)."""
    if len(description) > DESCRIPTION_MAX_LENGTH:
        description = description[:DESCRIPTION_MAX_LENGTH]
    suffix = f" [mutation: {reason[:100]}]"
    return description + suffix


def get_mutation_history(last_n=10):
    """Get recent mutation records for context."""
    state = read_state()
    return state.get("_mutation_history", [])[-last_n:]

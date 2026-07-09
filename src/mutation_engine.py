import json
from pathlib import Path

# Minimal mutation engine used by curator.py

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = BASE_DIR / "state.json"

# Supported parameters and step sizes
PARAMETER_SCHEMA = {
    "agent_temp": {"min": 0.1, "max": 1.0, "step": 0.05, "default": 0.85},
    "exploration_factor": {"min": 0.0, "max": 1.0, "step": 0.05, "default": 0.5},
}


def _clamp(val: float, p: str) -> float:
    lo = PARAMETER_SCHEMA[p]["min"]
    hi = PARAMETER_SCHEMA[p]["max"]
    return max(lo, min(hi, val))


def read_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_mutation(param_name: str, reason: str = "", cycle: int = 0):
    """Apply a small bounded change to a supported parameter.

    Returns: (ok: bool, desc: str)
    """
    p = param_name.strip()
    if p not in PARAMETER_SCHEMA:
        return False, f"неизвестный параметр: {p}"

    meta = PARAMETER_SCHEMA[p]
    step = meta["step"]

    state = read_state() or {}
    genome = state.get("_genome", {})
    cur = genome.get(p, meta["default"])
    try:
        cur_val = float(cur)
    except Exception:
        cur_val = meta["default"]

    # Simple oscillating update: bump up by step, clamp to max
    new_val = _clamp(cur_val + step, p)
    genome[p] = new_val
    state["_genome"] = genome
    _write_state(state)

    desc = f"{p} := {cur_val:.2f} → {new_val:.2f} (шаг {step:.2f})"
    if reason:
        desc += f"; причина: {reason[:60]}"
    return True, desc

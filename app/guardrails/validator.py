"""Deterministic guardrails between the LLM and the optimizer.

validate_and_sanitize() is a pure function that NEVER raises and ALWAYS
returns exactly len(notes) entries, indexed 0..N-1, each satisfying the
applies/no_op invariant. Anything the LLM got wrong is downgraded to a
transparent no_op rather than invented, silently dropped, or allowed to
crash the request.
"""

import math

ALLOWED_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}


def _is_finite_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _clean_hours(hours) -> list[int] | None:
    if not isinstance(hours, list) or len(hours) == 0:
        return None
    try:
        ints = [int(h) for h in hours]
    except (TypeError, ValueError):
        return None
    if any(isinstance(h, bool) for h in hours):
        return None
    if any(h < 0 or h > 23 for h in ints):
        return None
    cleaned = sorted(set(ints))
    return cleaned if cleaned else None


def _make_no_op(note_index: int, reason: str) -> dict:
    return {
        "note_index": note_index,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": "This note does not affect today's energy schedule.",
        "_guardrail_reason": reason,
    }


def _sanitize_entry(item: dict, idx: int, battery_capacity_kwh: float) -> dict:
    directive_type = item.get("directive_type")
    explanation = item.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        explanation = ""

    if directive_type not in ALLOWED_TYPES:
        return _make_no_op(idx, f"unsupported directive_type: {directive_type!r}")

    if directive_type == "no_op":
        return {
            "note_index": idx,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": explanation or "This note does not affect today's energy schedule.",
        }

    adjustment = item.get("structured_adjustment")
    if not isinstance(adjustment, dict):
        return _make_no_op(idx, "missing or malformed structured_adjustment")

    hours = _clean_hours(adjustment.get("hours"))
    if hours is None:
        return _make_no_op(idx, "invalid hours array")

    if directive_type == "solar_reduction":
        factor = adjustment.get("factor")
        if not _is_finite_number(factor) or not (0 <= factor <= 1):
            return _make_no_op(idx, f"invalid solar_reduction factor: {factor!r}")
        clean_adj = {"hours": hours, "factor": float(factor)}

    elif directive_type == "minimum_battery_reserve":
        min_energy = adjustment.get("minimum_energy_kwh")
        if not _is_finite_number(min_energy) or min_energy < 0 or min_energy > battery_capacity_kwh:
            return _make_no_op(idx, f"invalid minimum_energy_kwh: {min_energy!r}")
        clean_adj = {"hours": hours, "minimum_energy_kwh": float(min_energy)}

    elif directive_type in ("no_charge_window", "no_discharge_window"):
        clean_adj = {"hours": hours}

    elif directive_type == "max_grid_window":
        max_grid = adjustment.get("max_grid_kwh")
        if not _is_finite_number(max_grid) or max_grid < 0:
            return _make_no_op(idx, f"invalid max_grid_kwh: {max_grid!r}")
        clean_adj = {"hours": hours, "max_grid_kwh": float(max_grid)}

    else:  # unreachable given the ALLOWED_TYPES check above
        return _make_no_op(idx, "unreachable directive_type branch")

    return {
        "note_index": idx,
        "applies": True,
        "directive_type": directive_type,
        "structured_adjustment": clean_adj,
        "explanation": explanation or f"Applied {directive_type} for the stated hours.",
    }


def validate_and_sanitize(raw_output, notes: list[str], battery_capacity_kwh: float) -> list[dict]:
    n = len(notes)
    result: list[dict | None] = [None] * n

    if isinstance(raw_output, list):
        used_indices: set[int] = set()
        for item in raw_output:
            if not isinstance(item, dict):
                continue
            idx = item.get("note_index")
            if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0 or idx >= n or idx in used_indices:
                continue
            result[idx] = _sanitize_entry(item, idx, battery_capacity_kwh)
            used_indices.add(idx)

    for i in range(n):
        if result[i] is None:
            result[i] = _make_no_op(i, "missing from LLM output")

    # Final invariant re-check: absolute last safety net.
    for i, entry in enumerate(result):  # type: ignore[assignment]
        entry["note_index"] = i
        is_no_op = entry["directive_type"] == "no_op"
        if is_no_op:
            entry["applies"] = False
            entry["structured_adjustment"] = None
        else:
            entry["applies"] = True

    return result  # type: ignore[return-value]

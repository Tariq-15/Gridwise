"""Shared helpers that turn a validated directive_interpretation list into
per-hour effective constraints. Used identically by the LP optimizer, the
fallback heuristic, and the replay validator so all three agree on what
"active" means for a given hour.
"""

HOURS = range(24)


def compute_effective_solar(base_solar: list[float], directives: list[dict]) -> list[float]:
    effective = list(base_solar)
    for entry in directives:
        if entry["directive_type"] == "solar_reduction" and entry["applies"]:
            adj = entry["structured_adjustment"]
            factor = adj["factor"]
            for h in adj["hours"]:
                effective[h] = effective[h] * factor
    return effective


def compute_active_min_energy(base_minimum_energy_kwh: float, directives: list[dict]) -> list[float]:
    active = [base_minimum_energy_kwh] * 24
    for entry in directives:
        if entry["directive_type"] == "minimum_battery_reserve" and entry["applies"]:
            adj = entry["structured_adjustment"]
            reserve = adj["minimum_energy_kwh"]
            for h in adj["hours"]:
                active[h] = max(active[h], reserve)
    return active


def compute_no_charge_hours(directives: list[dict]) -> set[int]:
    hours: set[int] = set()
    for entry in directives:
        if entry["directive_type"] == "no_charge_window" and entry["applies"]:
            hours.update(entry["structured_adjustment"]["hours"])
    return hours


def compute_no_discharge_hours(directives: list[dict]) -> set[int]:
    hours: set[int] = set()
    for entry in directives:
        if entry["directive_type"] == "no_discharge_window" and entry["applies"]:
            hours.update(entry["structured_adjustment"]["hours"])
    return hours


def compute_max_grid_caps(directives: list[dict]) -> dict[int, float]:
    caps: dict[int, float] = {}
    for entry in directives:
        if entry["directive_type"] == "max_grid_window" and entry["applies"]:
            adj = entry["structured_adjustment"]
            cap = adj["max_grid_kwh"]
            for h in adj["hours"]:
                caps[h] = min(caps[h], cap) if h in caps else cap
    return caps

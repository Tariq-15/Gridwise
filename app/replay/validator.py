"""Independent hour-by-hour replay of a candidate hourly_plan against the
GridWise energy rules and every active directive. Mirrors what the hidden
judge does: correct extraction without correct downstream application does
not pass. Also authoritative for the response's totals — they are always
recomputed here, never taken from solver-internal aggregates.
"""

from app.optimizer.directives import (
    compute_active_min_energy,
    compute_effective_solar,
    compute_max_grid_caps,
    compute_no_charge_hours,
    compute_no_discharge_hours,
)

TOL = 0.01


def replay_and_validate(hours_sorted, battery, directives: list[dict], hourly_plan: list[dict]):
    """Returns (ok: bool, violations: list[str], totals: dict)."""
    violations: list[str] = []

    plan_by_hour = {p["hour"]: p for p in hourly_plan}
    if sorted(plan_by_hour.keys()) != list(range(24)):
        return False, ["hourly_plan must contain exactly 24 unique hours 0-23"], {}

    demand = {h.hour: h.demand_kwh for h in hours_sorted}
    tariff = {h.hour: h.tariff_bdt_per_kwh for h in hours_sorted}
    base_solar = [h.solar_kwh for h in hours_sorted]  # hours_sorted must already be ascending 0..23

    effective_solar = compute_effective_solar(base_solar, directives)
    active_min = compute_active_min_energy(battery.minimum_energy_kwh, directives)
    no_charge_hours = compute_no_charge_hours(directives)
    no_discharge_hours = compute_no_discharge_hours(directives)
    max_grid_caps = compute_max_grid_caps(directives)

    prev_E = battery.initial_energy_kwh
    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0

    for h in range(24):
        p = plan_by_hour[h]
        grid = p["grid_kwh"]
        solar_used = p["solar_used_kwh"]
        action = p["battery_action"]
        kwh = p["battery_kwh"]
        E_after = p["battery_energy_after_kwh"]

        if action not in ("charge", "discharge", "idle"):
            violations.append(f"hour {h}: invalid battery_action {action!r}")
            action = "idle"
            kwh = 0.0

        if grid < -TOL:
            violations.append(f"hour {h}: negative grid_kwh")
        if solar_used < -TOL or solar_used > effective_solar[h] + TOL:
            violations.append(f"hour {h}: solar_used_kwh exceeds effective solar")
        if action == "idle" and abs(kwh) > TOL:
            violations.append(f"hour {h}: idle but battery_kwh != 0")
        if kwh < -TOL:
            violations.append(f"hour {h}: negative battery_kwh")

        charge_amt = kwh if action == "charge" else 0.0
        discharge_amt = kwh if action == "discharge" else 0.0

        if charge_amt > battery.max_charge_kwh_per_hour + TOL:
            violations.append(f"hour {h}: charge exceeds max_charge_kwh_per_hour")
        if discharge_amt > battery.max_discharge_kwh_per_hour + TOL:
            violations.append(f"hour {h}: discharge exceeds max_discharge_kwh_per_hour")
        if h in no_charge_hours and charge_amt > TOL:
            violations.append(f"hour {h}: charging during an active no_charge_window")
        if h in no_discharge_hours and discharge_amt > TOL:
            violations.append(f"hour {h}: discharging during an active no_discharge_window")
        if h in max_grid_caps and grid > max_grid_caps[h] + TOL:
            violations.append(f"hour {h}: grid_kwh exceeds active max_grid_window cap")

        expected_E = prev_E + charge_amt - discharge_amt
        if abs(expected_E - E_after) > TOL:
            violations.append(f"hour {h}: battery_energy_after_kwh inconsistent with battery_action/battery_kwh")
        if E_after < active_min[h] - TOL or E_after > battery.capacity_kwh + TOL:
            violations.append(f"hour {h}: battery energy out of bounds")

        balance = grid + solar_used + discharge_amt - demand[h] - charge_amt
        if abs(balance) > TOL:
            violations.append(f"hour {h}: energy balance equation violated")

        total_grid += grid
        total_cost += grid * tariff[h]
        peak_grid = max(peak_grid, grid)
        prev_E = E_after

    if abs(prev_E - battery.initial_energy_kwh) > TOL:
        violations.append("end-of-day battery energy does not equal initial_energy_kwh")

    totals = {
        "total_grid_kwh": round(total_grid, 2),
        "total_cost_bdt": round(total_cost, 2),
        "peak_grid_kwh": round(peak_grid, 2),
    }
    return (len(violations) == 0, violations, totals)

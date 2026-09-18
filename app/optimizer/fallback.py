"""Deterministic fallback used ONLY if the LP fails to solve or its replay
check finds a violation (should be unreachable for organizer-valid feasible
scenarios). Guarantees a schema-valid, replay-checked 24-hour plan instead
of ever returning a 500 or an invalid body for a well-formed request.

Tier 2: greedy (solar -> battery -> grid) with a backward end-of-day
correction pass.
Tier 3 (last resort, should be unreachable): pure-grid, battery-idle plan.
"""

from app.optimizer.directives import (
    compute_active_min_energy,
    compute_effective_solar,
    compute_max_grid_caps,
    compute_no_charge_hours,
    compute_no_discharge_hours,
)

TOL = 1e-9


def greedy_fallback_plan(hours_sorted, battery, directives: list[dict]) -> list[dict]:
    demand = [h.demand_kwh for h in hours_sorted]
    solar = [h.solar_kwh for h in hours_sorted]

    effective_solar = compute_effective_solar(solar, directives)
    active_min = compute_active_min_energy(battery.minimum_energy_kwh, directives)
    no_charge_hours = compute_no_charge_hours(directives)
    no_discharge_hours = compute_no_discharge_hours(directives)
    max_grid_caps = compute_max_grid_caps(directives)

    charge = [0.0] * 24
    discharge = [0.0] * 24
    solar_for_demand = [0.0] * 24
    solar_for_charge = [0.0] * 24

    E = battery.initial_energy_kwh
    for h in range(24):
        s_demand = min(demand[h], effective_solar[h])
        remaining = demand[h] - s_demand
        d_amt = 0.0
        if remaining > TOL and h not in no_discharge_hours:
            headroom_down = max(0.0, E - active_min[h])
            d_amt = min(remaining, battery.max_discharge_kwh_per_hour, headroom_down)
            remaining -= d_amt

        leftover_solar = effective_solar[h] - s_demand
        c_amt = 0.0
        if leftover_solar > TOL and d_amt <= TOL and h not in no_charge_hours:
            headroom_up = max(0.0, battery.capacity_kwh - E)
            c_amt = min(leftover_solar, battery.max_charge_kwh_per_hour, headroom_up)

        solar_for_demand[h] = s_demand
        solar_for_charge[h] = c_amt
        discharge[h] = d_amt
        charge[h] = c_amt
        E = E + c_amt - d_amt

    _backward_correct(
        charge, discharge, battery, active_min, no_charge_hours, no_discharge_hours, effective_solar, demand
    )

    return _build_plan(
        demand, effective_solar, solar_for_demand, solar_for_charge, charge, discharge,
        battery.initial_energy_kwh, max_grid_caps,
    )


def _backward_correct(charge, discharge, battery, active_min, no_charge_hours, no_discharge_hours, effective_solar, demand):
    def final_energy():
        E = battery.initial_energy_kwh
        for h in range(24):
            E = E + charge[h] - discharge[h]
        return E

    diff = battery.initial_energy_kwh - final_energy()
    if abs(diff) <= 1e-6:
        return

    for h in range(23, -1, -1):
        if abs(diff) <= 1e-6:
            break
        if diff > 0:
            # need more net charge (or less net discharge) at hour h
            if discharge[h] > TOL:
                reduce_by = min(discharge[h], diff)
                discharge[h] -= reduce_by
                diff -= reduce_by
            elif h not in no_charge_hours:
                room = battery.max_charge_kwh_per_hour - charge[h]
                add = min(room, diff)
                if add > TOL:
                    charge[h] += add
                    diff -= add
        else:
            need = -diff
            if charge[h] > TOL:
                reduce_by = min(charge[h], need)
                charge[h] -= reduce_by
                diff += reduce_by
            elif h not in no_discharge_hours:
                room = battery.max_discharge_kwh_per_hour - discharge[h]
                add = min(room, need)
                if add > TOL:
                    discharge[h] += add
                    diff += add


def _build_plan(demand, effective_solar, solar_for_demand, solar_for_charge, charge, discharge, initial_energy_kwh, max_grid_caps):
    plan = []
    E = initial_energy_kwh
    for h in range(24):
        grid = demand[h] + charge[h] - solar_for_demand[h] - solar_for_charge[h] - discharge[h]
        grid = max(0.0, grid)
        if h in max_grid_caps and grid > max_grid_caps[h]:
            # last-resort clamp; replay will catch this if it makes the plan infeasible,
            # escalating to the tier-3 pure-grid plan.
            grid = max_grid_caps[h]
        solar_used = solar_for_demand[h] + solar_for_charge[h]
        E = E + charge[h] - discharge[h]

        if charge[h] > TOL:
            action, kwh = "charge", round(charge[h], 2)
        elif discharge[h] > TOL:
            action, kwh = "discharge", round(discharge[h], 2)
        else:
            action, kwh = "idle", 0.0

        plan.append(
            {
                "hour": h,
                "grid_kwh": round(grid, 2),
                "solar_used_kwh": round(solar_used, 2),
                "battery_action": action,
                "battery_kwh": kwh,
                "battery_energy_after_kwh": round(E, 2),
            }
        )
    return plan


def last_resort_plan(hours_sorted, battery, directives: list[dict]) -> list[dict]:
    """Pure-grid, battery-idle-all-day. Exists only to guarantee a schema-valid
    HTTP 200 under any circumstance; not a scored strategy."""
    demand = [h.demand_kwh for h in hours_sorted]
    solar = [h.solar_kwh for h in hours_sorted]
    effective_solar = compute_effective_solar(solar, directives)

    plan = []
    for h in range(24):
        solar_used = min(demand[h], effective_solar[h])
        grid = max(0.0, demand[h] - solar_used)
        plan.append(
            {
                "hour": h,
                "grid_kwh": round(grid, 2),
                "solar_used_kwh": round(solar_used, 2),
                "battery_action": "idle",
                "battery_kwh": 0.0,
                "battery_energy_after_kwh": round(battery.initial_energy_kwh, 2),
            }
        )
    return plan

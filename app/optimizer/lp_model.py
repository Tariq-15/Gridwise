"""Builds and solves the 24-hour scheduling LP with scipy.optimize.linprog
(HiGHS). Pure-Python-callable solver, no external binary — avoids the
"solver not found in container" class of deployment risk.
"""

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog

from app.optimizer.directives import (
    compute_active_min_energy,
    compute_effective_solar,
    compute_max_grid_caps,
    compute_no_charge_hours,
    compute_no_discharge_hours,
)

N = 24
EPS = 1e-6  # tie-break weight on charge+discharge; negligible next to real BDT cost


def _idx_grid(h: int) -> int:
    return h


def _idx_solar(h: int) -> int:
    return N + h


def _idx_charge(h: int) -> int:
    return 2 * N + h


def _idx_discharge(h: int) -> int:
    return 3 * N + h


def _idx_E(h: int) -> int:
    return 4 * N + h


@dataclass
class LPSolution:
    grid: list[float]
    solar_used: list[float]
    charge: list[float]
    discharge: list[float]
    battery_energy_after: list[float]
    effective_solar: list[float]


def solve_lp(hours_sorted, battery, directives: list[dict]) -> LPSolution | None:
    """hours_sorted: list of HourEntry-like objects with .hour/.demand_kwh/.solar_kwh/.tariff_bdt_per_kwh,
    already sorted ascending by hour 0..23."""
    demand = [h.demand_kwh for h in hours_sorted]
    solar = [h.solar_kwh for h in hours_sorted]
    tariff = [h.tariff_bdt_per_kwh for h in hours_sorted]

    effective_solar = compute_effective_solar(solar, directives)
    active_min = compute_active_min_energy(battery.minimum_energy_kwh, directives)
    no_charge_hours = compute_no_charge_hours(directives)
    no_discharge_hours = compute_no_discharge_hours(directives)
    max_grid_caps = compute_max_grid_caps(directives)

    n_vars = 5 * N
    c = np.zeros(n_vars)
    for h in range(N):
        c[_idx_grid(h)] = tariff[h]
        c[_idx_charge(h)] = EPS
        c[_idx_discharge(h)] = EPS

    bounds: list[tuple[float, float | None]] = [(0.0, None)] * n_vars
    for h in range(N):
        bounds[_idx_grid(h)] = (0.0, None)
        bounds[_idx_solar(h)] = (0.0, max(0.0, effective_solar[h]))
        charge_ub = 0.0 if h in no_charge_hours else battery.max_charge_kwh_per_hour
        bounds[_idx_charge(h)] = (0.0, charge_ub)
        discharge_ub = 0.0 if h in no_discharge_hours else battery.max_discharge_kwh_per_hour
        bounds[_idx_discharge(h)] = (0.0, discharge_ub)
        lo = min(active_min[h], battery.capacity_kwh)
        bounds[_idx_E(h)] = (lo, battery.capacity_kwh)

    A_eq = []
    b_eq = []

    for h in range(N):
        row = np.zeros(n_vars)
        row[_idx_grid(h)] = 1.0
        row[_idx_solar(h)] = 1.0
        row[_idx_discharge(h)] = 1.0
        row[_idx_charge(h)] = -1.0
        A_eq.append(row)
        b_eq.append(demand[h])

    for h in range(N):
        row = np.zeros(n_vars)
        row[_idx_E(h)] = 1.0
        row[_idx_charge(h)] = -1.0
        row[_idx_discharge(h)] = 1.0
        if h == 0:
            b_eq.append(battery.initial_energy_kwh)
        else:
            row[_idx_E(h - 1)] = -1.0
            b_eq.append(0.0)
        A_eq.append(row)

    row = np.zeros(n_vars)
    row[_idx_E(N - 1)] = 1.0
    A_eq.append(row)
    b_eq.append(battery.initial_energy_kwh)

    A_ub = []
    b_ub = []
    for h, cap in max_grid_caps.items():
        row = np.zeros(n_vars)
        row[_idx_grid(h)] = 1.0
        A_ub.append(row)
        b_ub.append(cap)

    result = linprog(
        c,
        A_eq=np.array(A_eq),
        b_eq=np.array(b_eq),
        A_ub=np.array(A_ub) if A_ub else None,
        b_ub=np.array(b_ub) if b_ub else None,
        bounds=bounds,
        method="highs",
    )

    if not result.success:
        return None

    x = result.x
    return LPSolution(
        grid=[float(x[_idx_grid(h)]) for h in range(N)],
        solar_used=[float(x[_idx_solar(h)]) for h in range(N)],
        charge=[float(x[_idx_charge(h)]) for h in range(N)],
        discharge=[float(x[_idx_discharge(h)]) for h in range(N)],
        battery_energy_after=[float(x[_idx_E(h)]) for h in range(N)],
        effective_solar=effective_solar,
    )

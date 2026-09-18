"""Regression harness against the 10 public GridWise sample cases.

Deliberately reimplements the constraint-replay logic independently of
app/replay/validator.py (mirrors "the judge independently replays" — a
shared bug in the app's own checker should not be able to hide itself).

Usage:
    python tests/regression/run_public_samples.py [base_url]
    (default base_url: http://localhost:8000)
"""

import json
import sys
import time
from pathlib import Path

import httpx

TOL = 0.01
FIXTURE = Path(__file__).parent / "fixtures" / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"


def load_cases():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data["cases"]


def compute_effective_solar(base_solar, directive_interpretation):
    effective = list(base_solar)
    for e in directive_interpretation:
        if e["directive_type"] == "solar_reduction" and e["applies"]:
            adj = e["structured_adjustment"]
            for h in adj["hours"]:
                effective[h] = effective[h] * adj["factor"]
    return effective


def compute_active_min(base_min, directive_interpretation):
    active = [base_min] * 24
    for e in directive_interpretation:
        if e["directive_type"] == "minimum_battery_reserve" and e["applies"]:
            adj = e["structured_adjustment"]
            for h in adj["hours"]:
                active[h] = max(active[h], adj["minimum_energy_kwh"])
    return active


def compute_no_charge(directive_interpretation):
    s = set()
    for e in directive_interpretation:
        if e["directive_type"] == "no_charge_window" and e["applies"]:
            s.update(e["structured_adjustment"]["hours"])
    return s


def compute_no_discharge(directive_interpretation):
    s = set()
    for e in directive_interpretation:
        if e["directive_type"] == "no_discharge_window" and e["applies"]:
            s.update(e["structured_adjustment"]["hours"])
    return s


def compute_max_grid(directive_interpretation):
    caps = {}
    for e in directive_interpretation:
        if e["directive_type"] == "max_grid_window" and e["applies"]:
            adj = e["structured_adjustment"]
            for h in adj["hours"]:
                caps[h] = min(caps.get(h, adj["max_grid_kwh"]), adj["max_grid_kwh"])
    return caps


def independent_replay(scenario_input, ground_truth_directives, hourly_plan):
    hours = sorted(scenario_input["hours"], key=lambda h: h["hour"])
    battery = scenario_input["battery"]
    demand = {h["hour"]: h["demand_kwh"] for h in hours}
    tariff = {h["hour"]: h["tariff_bdt_per_kwh"] for h in hours}
    base_solar = [h["solar_kwh"] for h in hours]

    effective_solar = compute_effective_solar(base_solar, ground_truth_directives)
    active_min = compute_active_min(battery["minimum_energy_kwh"], ground_truth_directives)
    no_charge = compute_no_charge(ground_truth_directives)
    no_discharge = compute_no_discharge(ground_truth_directives)
    max_grid = compute_max_grid(ground_truth_directives)

    plan_by_hour = {p["hour"]: p for p in hourly_plan}
    violations = []
    if sorted(plan_by_hour.keys()) != list(range(24)):
        return ["hourly_plan does not contain exactly 24 unique hours 0-23"], {}

    prev_E = battery["initial_energy_kwh"]
    total_grid = total_cost = peak_grid = 0.0

    for h in range(24):
        p = plan_by_hour[h]
        grid, solar_used = p["grid_kwh"], p["solar_used_kwh"]
        action, kwh, E_after = p["battery_action"], p["battery_kwh"], p["battery_energy_after_kwh"]
        charge_amt = kwh if action == "charge" else 0.0
        discharge_amt = kwh if action == "discharge" else 0.0

        if solar_used > effective_solar[h] + TOL:
            violations.append(f"hour {h}: solar_used exceeds effective solar")
        if charge_amt > battery["max_charge_kwh_per_hour"] + TOL:
            violations.append(f"hour {h}: charge exceeds rate limit")
        if discharge_amt > battery["max_discharge_kwh_per_hour"] + TOL:
            violations.append(f"hour {h}: discharge exceeds rate limit")
        if h in no_charge and charge_amt > TOL:
            violations.append(f"hour {h}: charged during no_charge_window")
        if h in no_discharge and discharge_amt > TOL:
            violations.append(f"hour {h}: discharged during no_discharge_window")
        if h in max_grid and grid > max_grid[h] + TOL:
            violations.append(f"hour {h}: grid exceeds max_grid_window cap")
        expected_E = prev_E + charge_amt - discharge_amt
        if abs(expected_E - E_after) > TOL:
            violations.append(f"hour {h}: battery_energy_after_kwh inconsistent")
        if E_after < active_min[h] - TOL or E_after > battery["capacity_kwh"] + TOL:
            violations.append(f"hour {h}: battery energy out of bounds")
        balance = grid + solar_used + discharge_amt - demand[h] - charge_amt
        if abs(balance) > TOL:
            violations.append(f"hour {h}: energy balance violated")

        total_grid += grid
        total_cost += grid * tariff[h]
        peak_grid = max(peak_grid, grid)
        prev_E = E_after

    if abs(prev_E - battery["initial_energy_kwh"]) > TOL:
        violations.append("end-of-day battery energy != initial_energy_kwh")

    totals = {"total_grid_kwh": round(total_grid, 2), "total_cost_bdt": round(total_cost, 2), "peak_grid_kwh": round(peak_grid, 2)}
    return violations, totals


def compare_interpretation(expected, actual):
    problems = []
    exp_by_idx = {e["note_index"]: e for e in expected}
    act_by_idx = {a["note_index"]: a for a in actual}
    if set(exp_by_idx) != set(range(len(expected))) or set(act_by_idx) != set(range(len(expected))):
        problems.append("note_index coverage mismatch")
        return problems
    for idx, exp in exp_by_idx.items():
        act = act_by_idx[idx]
        if act["applies"] != exp["applies"] or act["directive_type"] != exp["directive_type"]:
            problems.append(f"note {idx}: expected {exp['directive_type']}/applies={exp['applies']}, got {act['directive_type']}/applies={act['applies']}")
            continue
        if exp["directive_type"] == "no_op":
            continue
        exp_adj, act_adj = exp["structured_adjustment"], act.get("structured_adjustment") or {}
        if set(exp_adj["hours"]) != set(act_adj.get("hours", [])):
            problems.append(f"note {idx}: hours mismatch expected={exp_adj['hours']} got={act_adj.get('hours')}")
        for key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
            if key in exp_adj:
                act_val = act_adj.get(key)
                if act_val is None or abs(act_val - exp_adj[key]) > TOL:
                    problems.append(f"note {idx}: {key} mismatch expected={exp_adj[key]} got={act_val}")
    return problems


def run(base_url: str):
    cases = load_cases()
    failures = 0
    latencies = []

    with httpx.Client(timeout=35.0) as client:
        for case in cases:
            case_id = case["id"]
            t0 = time.monotonic()
            try:
                resp = client.post(f"{base_url}/optimize-energy", json=case["input"])
            except Exception as exc:  # noqa: BLE001
                print(f"[FAIL] {case_id}: request error {exc}")
                failures += 1
                continue
            latency_ms = (time.monotonic() - t0) * 1000
            latencies.append(latency_ms)

            if resp.status_code != 200:
                print(f"[FAIL] {case_id}: HTTP {resp.status_code}: {resp.text[:200]}")
                failures += 1
                continue

            body = resp.json()
            case_problems = []

            n_notes = len(case["input"]["operator_notes"])
            if len(body.get("directive_interpretation", [])) != n_notes:
                case_problems.append("directive_interpretation length mismatch")
            if len(body.get("hourly_plan", [])) != 24:
                case_problems.append("hourly_plan length != 24")
            if body.get("scenario_id") != case["input"]["scenario_id"]:
                case_problems.append("scenario_id echo mismatch")

            case_problems += compare_interpretation(
                case["expected_output"]["directive_interpretation"], body.get("directive_interpretation", [])
            )

            ground_truth_directives = case["expected_output"]["directive_interpretation"]
            violations, recomputed_totals = independent_replay(
                case["input"], ground_truth_directives, body.get("hourly_plan", [])
            )
            case_problems += [f"replay: {v}" for v in violations]

            for key in ("total_grid_kwh", "total_cost_bdt", "peak_grid_kwh"):
                reported = body.get(key)
                recomputed = recomputed_totals.get(key)
                if reported is None or recomputed is None or abs(reported - recomputed) > TOL:
                    case_problems.append(f"{key} mismatch: reported={reported} recomputed={recomputed}")

            expected_cost = case["expected_output"]["total_cost_bdt"]
            actual_cost = body.get("total_cost_bdt", float("inf"))
            if expected_cost > 0 and actual_cost / expected_cost > 1.10:
                case_problems.append(f"cost notably worse than reference: got {actual_cost}, reference {expected_cost}")

            if case_problems:
                failures += 1
                print(f"[FAIL] {case_id} ({latency_ms:.0f}ms):")
                for p in case_problems:
                    print(f"    - {p}")
            else:
                print(f"[PASS] {case_id} ({latency_ms:.0f}ms) cost={body.get('total_cost_bdt')} (ref={expected_cost})")

    print()
    if latencies:
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        print(f"Latency p50={p50:.0f}ms p95={p95:.0f}ms")
    print(f"{len(cases) - failures}/{len(cases)} passed")
    return failures


if __name__ == "__main__":
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    failures = run(base_url.rstrip("/"))
    sys.exit(1 if failures else 0)

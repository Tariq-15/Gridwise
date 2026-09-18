"""Wires the full pipeline: LLM -> guardrails -> LP optimizer -> netting ->
replay -> (fallback ladder if needed) -> response dict. This is the only
module the /optimize-energy route calls into.
"""

from app.guardrails.validator import validate_and_sanitize
from app.llm.factory import interpret_notes
from app.logging_utils import get_logger
from app.optimizer.fallback import greedy_fallback_plan, last_resort_plan
from app.optimizer.lp_model import solve_lp
from app.optimizer.netting import net_and_snap, snap_and_round
from app.replay.validator import replay_and_validate

logger = get_logger(__name__)


def _build_plan_from_lp(lp_solution, initial_energy_kwh: float) -> list[dict]:
    actions, kwh, energy_after = net_and_snap(lp_solution.charge, lp_solution.discharge, initial_energy_kwh)
    grid = snap_and_round(lp_solution.grid)
    solar_used = snap_and_round(lp_solution.solar_used)
    plan = []
    for h in range(24):
        plan.append(
            {
                "hour": h,
                "grid_kwh": grid[h],
                "solar_used_kwh": solar_used[h],
                "battery_action": actions[h],
                "battery_kwh": kwh[h],
                "battery_energy_after_kwh": energy_after[h],
            }
        )
    return plan


def _build_plan_summary(directive_interpretation: list[dict]) -> str:
    applied = [e for e in directive_interpretation if e["applies"]]
    if not applied:
        return "No operator directives applied; schedule optimized against base demand, solar, and tariff."
    types = sorted({e["directive_type"] for e in applied})
    return (
        f"Applied {len(applied)} operator directive(s) ({', '.join(types)}) "
        "and optimized the remaining 24-hour schedule for minimum grid cost."
    )


def _strip_internal(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if not k.startswith("_")}


async def handle_request(scenario) -> dict:
    hours_sorted = sorted(scenario.hours, key=lambda h: h.hour)
    battery = scenario.battery

    llm_result = await interpret_notes(scenario.operator_notes, battery.capacity_kwh)
    raw_entries = llm_result.raw_entries if llm_result.ok else []
    if not llm_result.ok:
        logger.warning("LLM interpretation unavailable (%s); degrading all notes to no_op", llm_result.error)

    directive_interpretation = validate_and_sanitize(
        raw_entries, scenario.operator_notes, battery.capacity_kwh
    )

    plan = None
    totals = None

    lp_solution = solve_lp(hours_sorted, battery, directive_interpretation)
    if lp_solution is not None:
        candidate = _build_plan_from_lp(lp_solution, battery.initial_energy_kwh)
        ok, violations, candidate_totals = replay_and_validate(
            hours_sorted, battery, directive_interpretation, candidate
        )
        if ok:
            plan, totals = candidate, candidate_totals
        else:
            logger.warning("LP plan failed replay, falling back: %s", violations)

    if plan is None:
        candidate = greedy_fallback_plan(hours_sorted, battery, directive_interpretation)
        ok, violations, candidate_totals = replay_and_validate(
            hours_sorted, battery, directive_interpretation, candidate
        )
        if ok:
            plan, totals = candidate, candidate_totals
        else:
            logger.error("Greedy fallback failed replay, using last resort: %s", violations)

    if plan is None:
        candidate = last_resort_plan(hours_sorted, battery, directive_interpretation)
        ok, violations, candidate_totals = replay_and_validate(
            hours_sorted, battery, directive_interpretation, candidate
        )
        plan, totals = candidate, candidate_totals
        if not ok:
            logger.error("Last resort plan still failed replay (unreachable case): %s", violations)

    return {
        "scenario_id": scenario.scenario_id,
        "directive_interpretation": [_strip_internal(e) for e in directive_interpretation],
        "hourly_plan": plan,
        "total_grid_kwh": totals["total_grid_kwh"],
        "total_cost_bdt": totals["total_cost_bdt"],
        "peak_grid_kwh": totals["peak_grid_kwh"],
        "plan_summary": _build_plan_summary(directive_interpretation),
    }

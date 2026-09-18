"""Post-processing: net any residual simultaneous charge+discharge from LP
solver numerics into a single signed action per hour, snap floating-point
noise, and derive the response's battery_action/battery_kwh fields.
"""

TOL = 1e-6


def _snap(x: float) -> float:
    if abs(x) < TOL:
        return 0.0
    nearest_int = round(x)
    if abs(x - nearest_int) < TOL:
        return float(nearest_int)
    return x


def net_and_snap(charge: list[float], discharge: list[float], initial_energy_kwh: float):
    """Returns (battery_action[], battery_kwh[], battery_energy_after[]) — all
    24-length, mathematically consistent with the netted charge/discharge."""
    actions = []
    kwh = []
    net_charge = []
    net_discharge = []

    for c, d in zip(charge, discharge):
        net = c - d
        if net > TOL:
            actions.append("charge")
            kwh.append(round(net, 6))
            net_charge.append(net)
            net_discharge.append(0.0)
        elif net < -TOL:
            actions.append("discharge")
            kwh.append(round(-net, 6))
            net_charge.append(0.0)
            net_discharge.append(-net)
        else:
            actions.append("idle")
            kwh.append(0.0)
            net_charge.append(0.0)
            net_discharge.append(0.0)

    energy_after = []
    prev = initial_energy_kwh
    for nc, nd in zip(net_charge, net_discharge):
        prev = prev + nc - nd
        energy_after.append(prev)

    kwh = [round(_snap(v), 2) for v in kwh]
    energy_after = [round(_snap(v), 2) for v in energy_after]
    return actions, kwh, energy_after


def snap_and_round(values: list[float]) -> list[float]:
    return [round(_snap(v), 2) for v in values]

"""Narrow, optional 422 checks: well-formed JSON matching the schema, but
violating a domain rule that isn't about JSON structure/shape. Kept
deliberately small per the Problem Statement's "422 optional" note.
"""


class SemanticValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def check_semantic_validity(scenario) -> None:
    b = scenario.battery
    if not (b.minimum_energy_kwh <= b.initial_energy_kwh <= b.capacity_kwh):
        raise SemanticValidationError(
            "battery.initial_energy_kwh must be between minimum_energy_kwh and capacity_kwh"
        )
    if b.minimum_energy_kwh > b.capacity_kwh:
        raise SemanticValidationError("battery.minimum_energy_kwh must not exceed capacity_kwh")

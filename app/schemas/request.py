from pydantic import BaseModel, Field, field_validator, model_validator


class HourEntry(BaseModel):
    hour: int = Field(ge=0, le=23)
    demand_kwh: float = Field(ge=0)
    solar_kwh: float = Field(ge=0)
    tariff_bdt_per_kwh: float = Field(ge=0)


class Battery(BaseModel):
    capacity_kwh: float = Field(gt=0)
    initial_energy_kwh: float = Field(ge=0)
    minimum_energy_kwh: float = Field(ge=0)
    max_charge_kwh_per_hour: float = Field(ge=0)
    max_discharge_kwh_per_hour: float = Field(ge=0)


class ScenarioRequest(BaseModel):
    scenario_id: str = Field(min_length=1)
    operator_notes: list[str] = Field(min_length=1, max_length=3)
    hours: list[HourEntry] = Field(min_length=24, max_length=24)
    battery: Battery

    @field_validator("operator_notes")
    @classmethod
    def notes_non_empty(cls, v: list[str]) -> list[str]:
        for note in v:
            if not note or not note.strip():
                raise ValueError("operator_notes entries must be non-empty strings")
        return v

    @model_validator(mode="after")
    def hours_cover_0_to_23(self) -> "ScenarioRequest":
        hour_values = [h.hour for h in self.hours]
        if len(set(hour_values)) != 24 or sorted(hour_values) != list(range(24)):
            raise ValueError("hours must contain exactly one unique entry for each hour 0 through 23")
        return self

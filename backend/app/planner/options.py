"""Planner inputs.

Every field is either a number the user must supply (default ``None``: no value
is invented) or an explicit, editable ASSUMPTION (``assumption=True``). The UI
renders its form from this schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Voltage = Literal["24VDC", "12VDC", "5VDC", "230VAC"]


def F(default, label, section, unit="", assumption=False, help="", **kw):  # noqa: A002
    return Field(default, json_schema_extra={"label": label, "section": section, "unit": unit,
                                             "assumption": assumption, "help": help}, **kw)


class Load(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    power_w: float = Field(gt=0, le=100000)
    voltage: Voltage = "24VDC"
    qty: int = Field(1, ge=1, le=1000)


class PlannerOptions(BaseModel):
    tier: Literal["low", "recommended", "professional"] = "recommended"
    vat_rate: float = F(0.21, "VAT rate", "Budget", "", True,
                        "Applied to prices quoted without VAT. Verify the current Romanian rate.", ge=0, le=0.5)

    # Layout
    soil_fraction: float = F(0.5, "Share of area under soil cultivation", "Layout", "0-1", True,
                             "Only used when both soil and hydroponics are enabled.", ge=0, le=1)
    climate_station_area_m2: float = F(100, "Area covered per climate station", "Climate", "m²", True,
                                       "Planning heuristic, not a standard.", gt=10, le=2000)
    min_climate_stations: int = F(2, "Minimum climate stations", "Climate", "", True,
                                  "Two allow cross-checking and redundancy.", ge=1, le=50)
    soil_probes_per_zone: int = F(2, "Soil probes per irrigation zone", "Soil", "", True, "", ge=1, le=20)
    hydro_tanks: int = F(1, "Nutrient tanks", "Hydroponics", "", False, "", ge=0, le=20)
    hydro_zones: int = F(1, "Hydroponic irrigation zones", "Hydroponics", "", False, "", ge=0, le=100)
    esp32_nodes: int = F(0, "Remote ESP32 nodes", "Controller", "", True,
                         "Zero = everything wired to the Pi / RS485.", ge=0, le=50)
    rs485_cable_m: float | None = F(None, "Total RS485 cable length", "Controller", "m", False,
                                    "Measure the planned route.", gt=0, le=1200)

    # Irrigation
    zone_max_area_m2: float = F(50, "Max soil area per irrigation zone", "Irrigation", "m²", True,
                                "Must be checked against pump flow and pressure.", gt=1, le=1000)
    pump_flow_l_min: float | None = F(None, "Pump flow at working pressure", "Irrigation", "L/min", False,
                                      "From the pump's datasheet curve.", gt=0)
    dripper_flow_l_h: float | None = F(None, "Dripper flow", "Irrigation", "L/h", False,
                                       "From the dripper's datasheet.", gt=0)
    dripper_spacing_m: float | None = F(None, "Dripper spacing", "Irrigation", "m", False, "", gt=0)
    drip_line_total_m: float | None = F(None, "Total drip line length (soil)", "Irrigation", "m", False,
                                        "Sum of all rows.", gt=0)
    run_minutes: float | None = F(None, "Irrigation run time per cycle", "Irrigation", "min", False, "", gt=0)
    water_l_per_m2_day: float | None = F(None, "Crop water demand", "Irrigation", "L/m²/day", False,
                                         "Your own estimate (the plant profiles deliberately give none).", gt=0)
    autonomy_days: float = F(1, "Reservoir autonomy", "Irrigation", "days", True, "", gt=0, le=60)

    # Ventilation
    ach_target: float | None = F(None, "Target air changes per hour", "Ventilation", "1/h", False,
                                 "Choose for your crop and climate.", gt=0, le=200)
    fan_flow_m3_h: float | None = F(None, "Exhaust fan rated airflow", "Ventilation", "m³/h", False,
                                    "Datasheet free-air value of the fan you plan to buy.", gt=0)
    fan_derating: float = F(0.7, "Fan derating (static pressure, screens)", "Ventilation", "0-1", True,
                            "Real flow is below free-air rating.", gt=0.1, le=1)
    circulation_fans: int | None = F(None, "Circulation fans", "Ventilation", "", False, "", ge=0, le=500)
    vent_actuators: int | None = F(None, "Motorised vent window actuators", "Ventilation", "", False,
                                   "Depends on window design.", ge=0, le=500)

    # Lighting
    dli_target: float | None = F(None, "Target DLI", "Lighting", "mol/m²/day", False, "", gt=0)
    natural_dli: float | None = F(None, "Natural DLI (measured)", "Lighting", "mol/m²/day", False,
                                  "Measure with a PAR sensor.", ge=0)
    photoperiod_h: float | None = F(None, "Photoperiod", "Lighting", "h", False, "", gt=0, le=24)
    fixture_ppf: float | None = F(None, "Fixture photon flux (PPF)", "Lighting", "µmol/s", False,
                                  "Datasheet value, not lumens.", gt=0)
    fixture_w: float | None = F(None, "Fixture power", "Lighting", "W", False, "", gt=0)
    light_fraction: float = F(1.0, "Share of area to light", "Lighting", "0-1", True, "", gt=0, le=1)
    light_utilisation: float = F(0.8, "Light utilisation factor", "Lighting", "0-1", True,
                                 "Fraction of fixture light that reaches the canopy.", gt=0.1, le=1)

    # Electrical
    psu_margin: float = F(0.25, "24 V supply headroom", "Electrical", "", True, "", ge=0, le=1)
    loads: list[Load] = []


FIELD_META = {name: f.json_schema_extra for name, f in PlannerOptions.model_fields.items()
              if f.json_schema_extra}

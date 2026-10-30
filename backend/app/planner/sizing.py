"""Sizing calculations. Pure functions; every result carries its status.

status: "final"       - all required inputs present
        "needs_input" - listed inputs missing, no number produced
Formulas are standard physics/geometry; numeric defaults that are not physics
are exposed as assumptions in PlannerOptions.
"""

from __future__ import annotations

import math

from app.planner.options import PlannerOptions
from app.services.greenhouse_config import GreenhouseConfig, GrowingMethod

COPPER_RESISTIVITY = 0.0175  # ohm*mm2/m, copper at about 20 C
STD_CROSS_SECTIONS_MM2 = [0.25, 0.34, 0.5, 0.75, 1.0, 1.5, 2.5, 4, 6, 10, 16, 25]
STD_FUSE_A = [0.5, 1, 2, 3.15, 4, 5, 6.3, 8, 10, 12.5, 16, 20, 25, 32]


def _out(missing: list[str], **values) -> dict:
    return {"status": "needs_input" if missing else "final", "missing": missing, **values}


def areas(cfg: GreenhouseConfig, o: PlannerOptions) -> dict:
    a = cfg.area_m2
    soil = GrowingMethod.SOIL in cfg.growing_methods
    hydro = GrowingMethod.HYDROPONIC in cfg.growing_methods
    if soil and hydro:
        s = round(a * o.soil_fraction, 2)
    else:
        s = a if soil else 0.0
    return {"total_m2": a, "soil_m2": s, "hydro_m2": round(a - s, 2) if (hydro or soil) else 0.0,
            "assumption": "soil/hydro split is an assumption" if soil and hydro else None}


def climate_stations(cfg: GreenhouseConfig, o: PlannerOptions) -> int:
    return max(o.min_climate_stations, math.ceil(cfg.area_m2 / o.climate_station_area_m2))


def irrigation(cfg: GreenhouseConfig, o: PlannerOptions) -> dict:
    ar = areas(cfg, o)
    soil_zones = math.ceil(ar["soil_m2"] / o.zone_max_area_m2) if ar["soil_m2"] > 0 else 0
    missing: list[str] = []
    res: dict = {"soil_zones": soil_zones, "hydro_zones": o.hydro_zones if ar["hydro_m2"] > 0 else 0,
                 "soil_area_m2": ar["soil_m2"], "hydro_area_m2": ar["hydro_m2"]}
    if None in (o.dripper_spacing_m, o.drip_line_total_m):
        missing += ["dripper_spacing_m", "drip_line_total_m"]
    else:
        res["drippers"] = math.ceil(o.drip_line_total_m / o.dripper_spacing_m)
    if o.dripper_flow_l_h is None:
        missing.append("dripper_flow_l_h")
    if not missing:
        total_flow = res["drippers"] * o.dripper_flow_l_h
        res["all_drippers_flow_l_h"] = round(total_flow, 1)
        res["flow_per_soil_zone_l_h"] = round(total_flow / soil_zones, 1) if soil_zones else 0
        if o.pump_flow_l_min and soil_zones:
            per_zone = total_flow / soil_zones / 60  # L/min
            res["zones_simultaneously_supported"] = int(o.pump_flow_l_min // per_zone) if per_zone else None
            res["pump_note"] = ("Zone flow exceeds pump flow: not even one zone can run"
                                if o.pump_flow_l_min < per_zone else
                                "Pressure at the drippers is NOT checked here; use the pump curve.")
    # daily water volume: two independent estimates, both from user inputs
    if o.water_l_per_m2_day is not None:
        res["daily_water_l_from_demand"] = round(o.water_l_per_m2_day * cfg.area_m2, 1)
    if "drippers" in res and o.dripper_flow_l_h is not None and o.run_minutes is not None:
        res["volume_per_cycle_l"] = round(res["drippers"] * o.dripper_flow_l_h * o.run_minutes / 60, 1)
    daily = res.get("daily_water_l_from_demand")
    if daily is not None:
        res["reservoir_min_l"] = round(daily * o.autonomy_days, 0)
    else:
        missing.append("water_l_per_m2_day")
    res["label"] = "Estimate from your inputs; not a crop recommendation."
    return _out(sorted(set(missing)), **res)


def ventilation(cfg: GreenhouseConfig, o: PlannerOptions) -> dict:
    missing = [] if cfg.height_m is not None else ["greenhouse height (Greenhouse page)"]
    if o.ach_target is None:
        missing.append("ach_target")
    res: dict = {"volume_m3": None, "fans": None}
    if cfg.height_m is not None:
        h = cfg.height_m
        geometry = "box volume (gutter height x floor area)"
        if cfg.ridge_height_m is not None and cfg.ridge_height_m > cfg.height_m:
            h = cfg.height_m + (cfg.ridge_height_m - cfg.height_m) / 2  # symmetric gable roof
            geometry = "gable roof assumed: gutter + half of (ridge - gutter)"
        res["volume_m3"] = round(cfg.area_m2 * h, 1)
        res["geometry"] = geometry
        if cfg.ridge_height_m is None:
            res["note"] = "Ridge height missing: roof space ignored, volume is underestimated."
    if o.ach_target is not None and res["volume_m3"] is not None:
        res["required_airflow_m3_h"] = round(res["volume_m3"] * o.ach_target, 0)
        if o.fan_flow_m3_h is None:
            missing.append("fan_flow_m3_h")
        else:
            usable = o.fan_flow_m3_h * o.fan_derating
            res["usable_flow_per_fan_m3_h"] = round(usable, 0)
            res["fans"] = math.ceil(res["required_airflow_m3_h"] / usable)
    res["note_geometry"] = ("Final sizing also needs vent opening areas and window geometry; "
                            "this is an air-volume based first estimate.")
    return _out(sorted(set(missing)), **res)


def lighting(cfg: GreenhouseConfig, o: PlannerOptions) -> dict:
    missing = [k for k in ("dli_target", "natural_dli", "photoperiod_h") if getattr(o, k) is None]
    res: dict = {"note": "PPFD/PPF are photon quantities; lux is not interchangeable with them."}
    if o.dli_target is not None and o.photoperiod_h is not None:
        res["target_ppfd_umol_m2_s"] = round(o.dli_target * 1e6 / (o.photoperiod_h * 3600), 1)
    if not missing:
        supp = max(0.0, o.dli_target - o.natural_dli)  # type: ignore[operator]
        res["supplemental_dli"] = round(supp, 2)
        ppfd = supp * 1e6 / (o.photoperiod_h * 3600)  # type: ignore[operator]
        res["supplemental_ppfd_umol_m2_s"] = round(ppfd, 1)
        lit = cfg.area_m2 * o.light_fraction
        flux = ppfd * lit / o.light_utilisation
        res["required_fixture_ppf_umol_s"] = round(flux, 0)
        if o.fixture_ppf is None:
            missing.append("fixture_ppf")
        else:
            res["fixtures"] = math.ceil(flux / o.fixture_ppf) if supp > 0 else 0
            if o.fixture_w is not None and res["fixtures"]:
                res["fixtures_power_w"] = round(res["fixtures"] * o.fixture_w, 0)
                res["energy_kwh_day"] = round(res["fixtures"] * o.fixture_w * o.photoperiod_h / 1000, 1)  # type: ignore[operator]
    return _out(sorted(set(missing)), **res)


def electrical(o: PlannerOptions) -> dict:
    totals: dict[str, float] = {}
    for ld in o.loads:
        totals[ld.voltage] = totals.get(ld.voltage, 0) + ld.power_w * ld.qty
    res: dict = {"totals_w": totals, "loads": len(o.loads)}
    if "24VDC" in totals:
        res["psu_24v_min_w"] = round(totals["24VDC"] * (1 + o.psu_margin), 0)
        fuses = []
        for ld in o.loads:
            if ld.voltage == "24VDC":
                i = ld.power_w / 24.0
                want = i * 1.25
                fuses.append({"load": ld.name, "current_a": round(i, 2),
                              "suggested_fuse_a": next((f for f in STD_FUSE_A if f >= want), None)})
        res["dc_fuse_suggestions"] = fuses
    if "230VAC" in totals:
        res["mains_note"] = ("230 V loads are listed for your electrician only. No breaker, RCD or "
                             "cable sizing is calculated for mains in this application.")
    res["safety"] = ("Conceptual values. Protective devices must be selected and installed by a "
                     "qualified person and be independent of this software.")
    return _out([] if o.loads else ["loads (add the equipment you plan to power)"], **res)


def cable(length_m: float, current_a: float, voltage_v: float, max_drop_pct: float = 3.0) -> dict:
    """Two-conductor DC run: drop = 2 * L * I * rho / A."""
    need = 2 * length_m * current_a * COPPER_RESISTIVITY / (voltage_v * max_drop_pct / 100)
    chosen = next((a for a in STD_CROSS_SECTIONS_MM2 if a >= need), None)
    drop_v = 2 * length_m * current_a * COPPER_RESISTIVITY / chosen if chosen else None
    return {"min_cross_section_mm2": round(need, 3), "suggested_mm2": chosen,
            "voltage_drop_v": round(drop_v, 3) if drop_v is not None else None,
            "voltage_drop_pct": round(drop_v / voltage_v * 100, 2) if drop_v is not None else None,
            "note": ("Voltage drop only. Cable current rating (ampacity), insulation, installation "
                     "method and protection must be checked separately by a qualified person.")}


def pi_recommendation() -> dict:
    return {
        "recommended": "Raspberry Pi 5 (4 GB) with active cooling and SSD or high-endurance storage",
        "basis": "Opinion for this software, not a measured benchmark.",
        "reasoning": [
            "This application (FastAPI + SQLite + MQTT broker) is light; a Pi 4 with 4 GB is sufficient.",
            "A Pi 5 costs more but adds CPU headroom for charts, reports and future modules, and its PCIe "
            "connector allows an NVMe SSD, which tolerates continuous writes better than microSD.",
            "2 GB models leave little room for the browser UI plus reports; 8 GB is not needed.",
            "Run it from an enclosure with a DC UPS or supervised shutdown: power cuts corrupt SD cards.",
        ],
        "alternatives": [
            {"name": "Raspberry Pi 4 (4 GB)", "when": "lowest cost; software runs fine"},
            {"name": "Industrial Raspberry-Pi-based controller (DIN-rail, wide-input supply)",
             "when": "professional tier; verify model and support before buying"},
        ],
        "power_note": "Use a supply rated for the board (the Pi 5 officially wants 5 V / 5 A for full USB power).",
    }

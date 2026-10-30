"""Built-in crop profiles.

PROVENANCE: general horticultural guidance. The ranges are intentionally broad,
are the sort of values commonly cited in greenhouse horticulture, and have NOT
been verified for a specific cultivar, substrate, climate or local trial.
Every value can be overridden (overrides are stored and shown as "user").
Water demand is deliberately NOT provided: it depends on climate, substrate and
system; set your own figure.
"""

from __future__ import annotations

import copy

PROVENANCE = ("General horticultural guidance: broad ranges commonly cited in greenhouse practice, compiled "
              "without a local trial. NOT verified for your cultivar, substrate or climate. Edit any value; "
              "your changes are marked as yours.")

WATER = {"l_per_m2_day": None,
         "note": "Not provided. Depends on climate, light, substrate and irrigation method. Enter your own figure."}


def rng(lo, hi):
    return {"min": lo, "max": hi}


def _p(id_, name, latin, category, temp, rh, vpd, dli, soil, hydro, germ, planting, transplanting, stages,
       harvest, pests, diseases, nutrients, notes=""):
    return {
        "id": id_, "name": name, "latin": latin, "category": category, "custom": False,
        "temperature_c": {"day_min": temp[0], "day_max": temp[1], "night_min": temp[2], "night_max": temp[3]},
        "humidity_rh": rng(*rh), "vpd_kpa": rng(*vpd),
        "light": {"dli_mol_m2_day": rng(*dli),
                  "note": "DLI is photons per m² per day; do not convert from lux."},
        "soil": {"ph": rng(*soil[0]), "ec_ms_cm": None, "notes": soil[1]},
        "hydroponic": {"ph": rng(*hydro[0]), "ec_ms_cm": rng(*hydro[1]), "solution_temp_c": rng(*hydro[2]),
                       "notes": hydro[3]},
        "germination": {"temp_c": rng(*germ[0]) if germ[0] else None, "days": rng(*germ[1]) if germ[1] else None,
                        "notes": germ[2]},
        "planting": planting, "transplanting": transplanting,
        "growth_stages": [{"name": n, "notes": t} for n, t in stages],
        "harvest": harvest, "pests": pests, "diseases": diseases, "nutrients": nutrients,
        "water": dict(WATER), "notes": notes,
    }


PROFILES: dict[str, dict] = {
    "tomato": _p(
        "tomato", "Tomato", "Solanum lycopersicum", "fruiting",
        (21, 26, 15, 18), (60, 80), (0.8, 1.2), (20, 30),
        ((6.0, 6.8), "Deep, well-drained, high organic matter; even moisture reduces blossom-end rot and fruit splitting."),
        ((5.8, 6.3), (2.0, 3.5), (18, 22), "EC is usually raised in the fruiting stage and lowered in hot, bright weather."),
        ((20, 27), (5, 10), "Warmth speeds germination; seedlings are grown on before transplanting."),
        "Raise seedlings in plugs or blocks; plant when roots have filled the block, deep enough to bury part of the stem.",
        "Harden off if moved from a different climate; support with string/clips from the first weeks.",
        [("Germination", "Seed to emerged seedling."), ("Seedling", "True leaves develop, kept warm and well lit."),
         ("Establishment", "After transplanting; roots colonise the substrate."),
         ("Vegetative", "Leaf and truss formation, side-shoot removal for indeterminate types."),
         ("Flowering and fruit set", "Pollination (vibration or bumblebees); avoid heat/humidity extremes."),
         ("Fruit development and ripening", "Harvest ripe trusses on a regular cycle.")],
        "Harvest at the colour stage your market requires; indeterminate types crop over many weeks.",
        ["Whitefly", "Aphids", "Spider mites", "Thrips", "Leaf miner (e.g. Tuta absoluta)", "Broad mite"],
        ["Grey mould (Botrytis)", "Leaf mould", "Late blight", "Powdery mildew", "Fusarium / Verticillium wilt",
         "Blossom-end rot (calcium transport disorder)"],
        "Nitrogen-led early, shifting towards potassium in fruiting; steady calcium and magnesium supply.",
    ),
    "cucumber": _p(
        "cucumber", "Cucumber", "Cucumis sativus", "fruiting",
        (22, 28, 18, 20), (70, 85), (0.7, 1.1), (15, 25),
        ((6.0, 6.8), "Light, fertile, well-drained; shallow roots dislike water stress."),
        ((5.5, 6.0), (1.7, 2.5), (18, 22), "Fast-growing and sensitive to cold roots."),
        ((25, 30), (3, 6), "Fast, warm germination."),
        "Sow singly in blocks; plant when the first true leaves are well developed.",
        "Keep roots warm; avoid disturbing roots.",
        [("Germination", "Seed to seedling."), ("Seedling", "Short, quick stage."), ("Establishment", "Roots establish after planting."),
         ("Vegetative", "Rapid vine growth, train on a support."), ("Fruiting", "Continuous fruit set and harvest.")],
        "Harvest young, frequently; leaving fruit to over-mature slows further fruit set.",
        ["Spider mites", "Whitefly", "Aphids", "Thrips"],
        ["Powdery mildew", "Downy mildew", "Gummy stem blight", "Fusarium wilt", "Grey mould (Botrytis)"],
        "Heavy feeder; balanced N-K with regular calcium and magnesium.",
    ),
    "pepper": _p(
        "pepper", "Sweet pepper", "Capsicum annuum", "fruiting",
        (22, 28, 16, 20), (60, 75), (0.8, 1.3), (18, 28),
        ((6.0, 6.8), "Well-drained fertile soil; even moisture prevents blossom-end rot."),
        ((5.8, 6.3), (2.0, 3.0), (18, 22), "Sensitive to salt and to uneven watering."),
        ((25, 30), (7, 14), "Slow, warmth-dependent germination."),
        "Raise in plugs; plant on raised beds or in substrate.",
        "Avoid cold nights after planting; support plants.",
        [("Germination", "Seed to seedling."), ("Seedling", "Slow early growth."), ("Establishment", "Roots establish after planting."),
         ("Vegetative", "Frame and leaf formation."), ("Flowering and fruit set", "Flowers can drop in heat stress."),
         ("Fruit development and ripening", "Green or coloured harvest depending on market.")],
        "Pick at the size/colour required; regular picking encourages more fruit.",
        ["Aphids", "Thrips", "Whitefly", "Spider mites", "Broad mite"],
        ["Grey mould (Botrytis)", "Powdery mildew", "Phytophthora blight", "Bacterial spot", "Blossom-end rot"],
        "Moderate nitrogen; potassium and calcium important in fruiting.",
    ),
    "lettuce": _p(
        "lettuce", "Lettuce", "Lactuca sativa", "leafy",
        (16, 22, 10, 14), (50, 70), (0.6, 1.0), (12, 17),
        ((6.0, 7.0), "Light, fertile, moisture-retentive soil; shallow roots."),
        ((5.5, 6.5), (0.8, 1.8), (18, 22), "Keep solution cool: warm solution encourages root disease."),
        ((15, 22), (2, 7), "Light-sensitive and slows above about 25 C."),
        "Direct sow or plug; space for the head type grown.",
        "Transplant young; keep the growing point at the surface.",
        [("Germination", "Seed to seedling."), ("Seedling", "Cool and bright."), ("Rosette growth", "Rapid leaf expansion."),
         ("Head formation", "Heading types only."), ("Harvest", "Before bolting or tip-burn.")],
        "Cut or pull at market size before bolting; harvest in the cool of the day.",
        ["Aphids", "Thrips", "Caterpillars", "Slugs"],
        ["Grey mould (Botrytis)", "Downy mildew", "Sclerotinia", "Tip-burn (calcium disorder)", "Pythium root rot (hydroponics)"],
        "Low to moderate feed; excess nitrogen and warmth favour tip-burn and bolting.",
    ),
    "spinach": _p(
        "spinach", "Spinach", "Spinacia oleracea", "leafy",
        (15, 20, 8, 12), (50, 70), (0.6, 1.0), (12, 17),
        ((6.0, 7.0), "Fertile, well-drained, avoid acid soils."),
        ((5.8, 6.5), (1.8, 2.3), (15, 20), "A cool-season crop; warm solution and long days trigger bolting."),
        ((10, 20), (5, 10), "Germinates poorly above about 25 C."),
        "Direct sow in rows or sow densely for baby leaf.",
        "Rarely transplanted.",
        [("Germination", "Seed to seedling."), ("Leaf growth", "Rosette expansion."), ("Harvest", "Before bolting.")],
        "Cut baby leaf or whole rosettes before flower stalks develop.",
        ["Aphids", "Leaf miners"],
        ["Downy mildew", "Damping off", "White rust", "Fusarium wilt"],
        "Responds to nitrogen; avoid excessive nitrate accumulation in dull, cool conditions.",
    ),
    "basil": _p(
        "basil", "Basil (herbs)", "Ocimum basilicum", "herb",
        (20, 28, 16, 20), (40, 70), (0.8, 1.2), (15, 20),
        ((5.8, 6.8), "Light, fertile, well-drained."),
        ((5.5, 6.5), (1.0, 1.6), (18, 24), "Chill-sensitive; below about 12 C leaves blacken."),
        ((20, 25), (5, 10), "Warm germination."),
        "Sow in plugs or direct; pinch tips to encourage branching.",
        "Keep warm; avoid chilling.",
        [("Germination", "Seed to seedling."), ("Vegetative", "Leaf production; pinch to branch."), ("Harvest", "Cut tops regularly, remove flower buds.")],
        "Cut above a leaf pair; remove flowers to keep leaf quality.",
        ["Aphids", "Whitefly", "Thrips"],
        ["Downy mildew", "Fusarium wilt", "Grey mould (Botrytis)"],
        "Moderate nitrogen for leaf growth.",
        "Other herbs (parsley, coriander, mint, chives) differ; duplicate this profile as a custom crop and edit it.",
    ),
    "strawberry": _p(
        "strawberry", "Strawberry", "Fragaria x ananassa", "fruiting",
        (18, 24, 8, 14), (60, 75), (0.6, 1.0), (12, 20),
        ((5.5, 6.5), "Well-drained, organic, slightly acid; raised beds or substrate."),
        ((5.5, 6.2), (1.0, 1.8), (15, 20), "Salt-sensitive; keep EC modest."),
        (None, None, "Normally propagated from runners or bought plants, not sown."),
        "Plant crowns with the growing point at substrate level.",
        "Cold-stored or plug plants are planted at the right season for the variety.",
        [("Establishment", "Roots and crown develop."), ("Vegetative", "Leaves and runners."), ("Flowering", "Flower initiation depends on variety and day length."),
         ("Fruiting", "Fruit set and ripening."), ("Renovation or replant", "Depending on production system.")],
        "Pick fully coloured fruit frequently; remove rotten fruit.",
        ["Spider mites", "Aphids", "Thrips", "Vine weevil", "Slugs"],
        ["Grey mould (Botrytis)", "Powdery mildew", "Anthracnose", "Phytophthora crown rot"],
        "Moderate feed; potassium important in fruiting; avoid excess nitrogen.",
    ),
    "eggplant": _p(
        "eggplant", "Eggplant (aubergine)", "Solanum melongena", "fruiting",
        (22, 28, 16, 20), (60, 75), (0.8, 1.3), (15, 25),
        ((5.8, 6.8), "Warm, fertile, well-drained."),
        ((5.8, 6.3), (2.0, 2.5), (18, 22), "Warm-loving; sensitive to cold roots."),
        ((24, 30), (7, 14), "Needs warmth to germinate."),
        "Raise in plugs; plant when nights are warm enough.",
        "Avoid chilling; support plants.",
        [("Germination", "Seed to seedling."), ("Seedling", "Slow, warm."), ("Establishment", "Roots establish after planting."),
         ("Vegetative", "Frame growth."), ("Flowering and fruit set", "Flowers drop in cold or heat stress."), ("Fruiting", "Harvest glossy fruit.")],
        "Harvest while skin is glossy and seeds are still soft.",
        ["Spider mites", "Whitefly", "Aphids", "Thrips"],
        ["Verticillium wilt", "Grey mould (Botrytis)", "Phomopsis", "Bacterial wilt"],
        "Similar to tomato: potassium and calcium during fruiting.",
    ),
}

TOP_KEYS = set(next(iter(PROFILES.values())).keys())


def get_builtin(crop_id: str) -> dict | None:
    p = PROFILES.get(crop_id)
    return copy.deepcopy(p) if p else None


def deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def changed_paths(patch: dict, prefix: str = "") -> list[str]:
    paths = []
    for k, v in patch.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            paths += changed_paths(v, key + ".")
        else:
            paths.append(key)
    return paths


def validate_profile(p: dict, partial: bool = False) -> list[str]:
    """Structural checks; returns a list of problems."""
    errs: list[str] = []
    unknown = set(p) - TOP_KEYS
    if unknown:
        errs.append(f"unknown fields: {sorted(unknown)}")

    def walk(d, path):
        if not isinstance(d, dict):
            return
        if "min" in d and "max" in d and all(isinstance(d[k], (int, float)) for k in ("min", "max")):
            if d["min"] > d["max"]:
                errs.append(f"{path}: min {d['min']} is above max {d['max']}")
        for a, b in (("day_min", "day_max"), ("night_min", "night_max")):
            if a in d and b in d and isinstance(d[a], (int, float)) and isinstance(d[b], (int, float)) and d[a] > d[b]:
                errs.append(f"{path}: {a} is above {b}")
        for k, v in d.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0 and "temp" not in path and k != "temperature_c":
                errs.append(f"{path}.{k}: negative value")
            walk(v, f"{path}.{k}" if path else k)

    walk(p, "")
    if not partial:
        for need in ("id", "name", "temperature_c", "humidity_rh", "vpd_kpa", "light"):
            if need not in p:
                errs.append(f"missing field: {need}")
    for lst in ("pests", "diseases", "growth_stages"):
        if lst in p and not isinstance(p[lst], list):
            errs.append(f"{lst} must be a list")
    return errs

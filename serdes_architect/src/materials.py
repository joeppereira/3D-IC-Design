"""Single source of truth for channel dielectric and conductor properties.

Previously three modules carried their own tables with different keys and
different numbers: si_analyzer.py knew "Megtron_7" (3.5 dB/in), si_analyzer_v3.py
knew "Megtron7" (2.5 dB/in) and neither knew "Flyover" -- which is the material
the golden config actually names, so both silently fell back to a default.
"""
from __future__ import annotations

# Loss at Nyquist for a 224G-class link, dB per inch.
# dk/df are the wideband-Debye anchors; conductor_area_m2 sets the DC resistance.
MATERIALS: dict[str, dict] = {
    "FR4":       {"loss_per_inch": 11.6, "dk": 4.3, "df": 0.0200, "conductor_area_m2": 3.5e-9},
    "Megtron_7": {"loss_per_inch": 3.5,  "dk": 3.4, "df": 0.0020, "conductor_area_m2": 3.5e-9},
    "Twinax":    {"loss_per_inch": 0.44, "dk": 2.1, "df": 0.0005, "conductor_area_m2": 1.3e-8},
    "Silicon":   {"loss_per_inch": 1.2,  "dk": 11.9, "df": 0.0010, "conductor_area_m2": 2.0e-12},
    "Glass":     {"loss_per_inch": 0.8,  "dk": 5.5, "df": 0.0008, "conductor_area_m2": 2.0e-12},
}

# Spellings and trade names that must resolve to the same physics.
ALIASES = {
    "megtron7": "Megtron_7", "megtron_7": "Megtron_7", "megtron": "Megtron_7",
    "flyover": "Twinax",          # the flyover cable assembly is twinax
    "twinax": "Twinax", "fr4": "FR4", "fr-4": "FR4",
    "silicon": "Silicon", "si": "Silicon", "glass": "Glass",
    "hybrid_bond": "Silicon", "hybrid_bond_power_array": "Silicon",
}

DEFAULT = "Megtron_7"


def resolve(name: str | None) -> str:
    """Canonical material key. Never guesses silently -- unknown names raise."""
    if not name:
        return DEFAULT
    if name in MATERIALS:
        return name
    key = ALIASES.get(str(name).strip().lower().replace(" ", "_").replace("-", "_"))
    if key:
        return key
    raise KeyError(
        f"unknown channel material {name!r}; add it to serdes_architect/src/materials.py "
        f"(known: {sorted(MATERIALS)} plus aliases {sorted(ALIASES)})")


def resolve_or_default(name: str | None) -> tuple[str, bool]:
    """(key, was_resolved). For callers that must not raise."""
    try:
        return resolve(name), True
    except KeyError:
        return DEFAULT, False


def props(name: str | None) -> dict:
    return MATERIALS[resolve(name)]


def loss_per_inch(name: str | None) -> float:
    return props(name)["loss_per_inch"]

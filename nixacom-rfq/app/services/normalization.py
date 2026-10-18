"""
Deterministic normalization.

Per section 8: do not rely on the LLM alone for normalization.
Maintain explicit mapping tables for equipment, weight units, and
ports, and extend these tables as new variants are observed.
"""

import re

EQUIPMENT_MAP: dict[str, str] = {
    "40 hc": "40HC",
    "40' hc": "40HC",
    "40ft high cube": "40HC",
    "40hc": "40HC",
    "40 gp": "40GP",
    "40' gp": "40GP",
    "40ft standard": "40GP",
    "20 gp": "20GP",
    "20' gp": "20GP",
    "20ft standard": "20GP",
}

PORT_MAP: dict[str, dict[str, str]] = {
    "shanghai": {"name": "Shanghai", "port_code": "CNSHA"},
    "shanghai port": {"name": "Shanghai", "port_code": "CNSHA"},
    "cnsha": {"name": "Shanghai", "port_code": "CNSHA"},
    "long beach": {"name": "Long Beach", "port_code": "USLGB"},
    "lgb": {"name": "Long Beach", "port_code": "USLGB"},
    "uslgb": {"name": "Long Beach", "port_code": "USLGB"},
}


def normalize_equipment(raw: str) -> str | None:
    if not raw:
        return None
    return EQUIPMENT_MAP.get(raw.strip().lower())


def normalize_port(raw: str) -> dict[str, str] | None:
    if not raw:
        return None
    return PORT_MAP.get(raw.strip().lower())


def normalize_weight_kg(raw: str) -> float | None:
    """
    Parses variants like '12.48 MT', '12,480 KGS', '12,480 KG'
    into a float in kilograms.
    """
    if not raw:
        return None
    cleaned = raw.strip().lower().replace(",", "")
    match = re.match(r"([\d.]+)\s*(mt|kgs|kg)", cleaned)
    if not match:
        return None
    value, unit = match.groups()
    value = float(value)
    if unit == "mt":
        value *= 1000
    return value

"""
Deterministic parser for pasted spreadsheet rows (tab- or comma-separated, header + data).

No AI involved: every field value is read straight from a named column, and each one
carries a `source` saying which column and row it came from. UN/LOCODEs are taken from
the "(CNSHA)" part of "Shanghai, CN (CNSHA)".
"""

import csv
import io
import re
from typing import Any, Dict, List, Optional

LOCODE_RE = re.compile(r"\(([A-Za-z]{5})\)")
_NUMERIC = {"quantity": int, "cargo_weight_kg": float, "target_rate_usd": float}
_EXPECTED = ["rfq_id", "customer", "origin_port", "destination_port", "container_type",
             "quantity", "cargo_weight_kg", "commodity", "target_rate_usd", "notes"]


def _to_number(raw: str, cast):
    cleaned = re.sub(r"[^0-9.\-]", "", raw or "")
    if cleaned in ("", "-", "."):
        return None
    return cast(float(cleaned)) if cast is int else cast(cleaned)


def parse_rfq_table(text: str) -> Optional[List[Dict[str, Dict[str, Any]]]]:
    """Return one dict per data row ({field: {"value", "source"}}), or None if not a table."""
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    delimiter = "\t" if "\t" in lines[0] else ","
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    header = [h.strip().lower() for h in next(reader)]
    if not {"origin_port", "destination_port"} <= set(header):
        return None

    rows = []
    for row_no, cells in enumerate(reader, start=1):
        record: Dict[str, Dict[str, Any]] = {}
        for col, raw in zip(header, cells):
            raw = raw.strip()
            source = f"Column '{col}', data row {row_no} of pasted table"
            value: Any = raw or None
            if col in _NUMERIC and raw:
                value = _to_number(raw, _NUMERIC[col])
            record[col] = {"value": value, "source": source}
        for side in ("origin", "destination"):
            port = record.get(f"{side}_port", {}).get("value") or ""
            match = LOCODE_RE.search(port)
            record[f"{side}_code"] = {
                "value": match.group(1).upper() if match else None,
                "source": (f"UN/LOCODE in brackets of column '{side}_port', data row {row_no}"
                           if match else f"No (XXXXX) UN/LOCODE found in column '{side}_port'"),
            }
        rows.append(record)
    return rows

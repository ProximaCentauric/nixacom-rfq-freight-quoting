"""
Pricing Trace
=============
For one RFQ, produce an ordered worksheet where EVERY number shows:
  - its value
  - the formula that produced it
  - where it came from (source)
  - its status: CUSTOMER_PROVIDED / <engine data status, e.g. PLACEHOLDER> /
                DERIVED / DERIVED_FROM_PLACEHOLDER / NOT_MODELED / MISSING

It also states plainly whether the result is fit to send to a customer
(`quote_ready`) and, if not, exactly what is blocking it.

Usage:
    python pricing_trace.py rfqs.csv [out.json]
CSV may be comma- or tab-separated. Expected columns:
    rfq_id, customer, origin_port, destination_port, container_type, quantity,
    cargo_weight_kg, commodity, target_rate_usd, notes
Ports should include a UN/LOCODE in parentheses, e.g. "Shanghai, CN (CNSHA)".
"""

import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from rate_benchmarks import DATA_STATUS_PLACEHOLDER, RateBenchmarkEngine

CUSTOMER = "CUSTOMER_PROVIDED"
DERIVED = "DERIVED"
DERIVED_PH = "DERIVED_FROM_PLACEHOLDER"
NOT_MODELED = "NOT_MODELED"
MISSING = "MISSING"


@dataclass
class TraceLine:
    step: int
    label: str
    value: Any
    formula: str
    source: str
    status: str
    as_of: Optional[str] = None


@dataclass
class PricingTrace:
    rfq_id: str
    customer: str
    lines: List[TraceLine]
    verdict: str
    quote_ready: bool
    blockers: List[str]


def _locode(text: Any) -> Optional[str]:
    """'Shanghai, CN (CNSHA)' -> 'CNSHA'. A bare 5-letter code also works."""
    text = str(text or "")
    m = re.search(r"\(([A-Za-z]{5})\)", text)
    if m:
        return m.group(1).upper()
    bare = re.sub(r"[^A-Za-z]", "", text)
    return bare.upper() if len(bare) == 5 else None


def _num(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _money(x: float) -> str:
    return f"{x:,.2f}"


def build_trace(engine: RateBenchmarkEngine, row: Dict[str, Any]) -> PricingTrace:
    lines: List[TraceLine] = []
    blockers: List[str] = []
    placeholder = engine.data_status == DATA_STATUS_PLACEHOLDER
    derived = DERIVED_PH if placeholder else DERIVED

    def add(label, value, formula, source, status, as_of=None):
        lines.append(TraceLine(len(lines) + 1, label, value, formula, source, status, as_of))

    origin_raw, dest_raw = row.get("origin_port", ""), row.get("destination_port", "")
    origin, dest = _locode(origin_raw), _locode(dest_raw)
    equipment = (row.get("container_type") or "").strip() or None
    qty_raw = _num(row.get("quantity"))
    target = _num(row.get("target_rate_usd"))
    target = target if (target is not None and target > 0) else None

    # 1-3: what the customer asked for
    if origin and dest:
        add("Lane (UN/LOCODE)", f"{origin}-{dest}",
            f"code read from '{origin_raw}' and '{dest_raw}'", "RFQ row", CUSTOMER)
    else:
        add("Lane (UN/LOCODE)", None, "no 5-letter UN/LOCODE found in port fields", "RFQ row", MISSING)
        blockers.append("Could not extract UN/LOCODE for origin and/or destination.")

    if qty_raw and qty_raw > 0:
        qty = int(qty_raw)
        add("Equipment", f"{qty} x {equipment or 'unspecified type'}", "quantity and container_type columns",
            "RFQ row", CUSTOMER)
    else:
        qty = 1
        add("Equipment", None, "quantity missing or invalid", "RFQ row", MISSING)
        blockers.append("Quantity missing or invalid.")

    # 4+: market reference
    result = engine.evaluate_target_rate(origin or "", dest or "", target, equipment, qty)
    if result.lane_found:
        add("Base ocean rate per 40ft", result.base_rate,
            f"lookup: lane table[{result.lane_key}]", engine.source_label, engine.data_status, engine.as_of)
        add("Fuel surcharge %", engine.fsc_pct, "single percentage applied to every lane",
            engine.fsc_source, engine.data_status, engine.as_of)
        add("Fuel surcharge per container", result.fuel_surcharge,
            f"{_money(result.base_rate)} x {engine.fsc_pct}%", "calculated", derived)
        add("Reference all-in per container", result.market_avg_rate,
            f"{_money(result.base_rate)} + {_money(result.fuel_surcharge)}", "calculated", derived)
        add(f"Reference total for {qty} container(s)", result.market_total,
            f"{_money(result.market_avg_rate)} x {qty}", "calculated", derived)
    else:
        add("Market reference", None, f"no entry for lane {result.lane_key}", engine.source_label, MISSING)
        blockers.append(f"No market reference for lane {result.lane_key}.")

    # customer target vs reference
    if target is not None:
        add("Customer target per container", target,
            "target_rate_usd column; ASSUMED per container, all-in USD", "RFQ row", CUSTOMER)
        add(f"Customer target total for {qty} container(s)", round(target * qty, 2),
            f"{_money(target)} x {qty}", "calculated", DERIVED)
        if result.lane_found:
            add("Variance vs reference", f"{result.variance_pct}%",
                f"({_money(target)} - {_money(result.market_avg_rate)}) / {_money(result.market_avg_rate)} x 100",
                "calculated", derived)
            add("Competitiveness", result.competitiveness,
                f"within +/-{engine.FAIR_BAND_PCT:.0f}% = FAIR, below = BELOW_MARKET, above = ABOVE_MARKET",
                "rule in rate_benchmarks.py", derived)
    else:
        add("Customer target per container", None, "no usable target_rate_usd in RFQ", "RFQ row", MISSING)

    # what is NOT in the price yet
    add("Carrier buy rate (our cost)", None, "no carrier cost source connected", "none", NOT_MODELED)
    add("Margin rule", None, "no margin rule defined", "none", NOT_MODELED)
    add("Surcharges and local charges (THC, docs, etc.)", None, "not modelled", "none", NOT_MODELED)
    blockers += ["No carrier buy rate source (sell price cannot be built).", "No margin rule defined."]
    notes = (row.get("notes") or "").strip()
    if notes:
        add("Customer terms in notes", notes, "free text; not priced", "RFQ row", NOT_MODELED)
        blockers.append("Customer terms in notes (for example, free time) are not reflected in any price.")
    if placeholder:
        blockers.insert(0, "Market reference is placeholder data (no verified source or date).")

    verdict = result.competitiveness if result.lane_found else "NO_REFERENCE"
    return PricingTrace(
        rfq_id=str(row.get("rfq_id", "")), customer=str(row.get("customer", "")),
        lines=lines, verdict=verdict, quote_ready=not blockers, blockers=blockers,
    )


def format_trace(t: PricingTrace) -> str:
    out = [f"{t.rfq_id} | {t.customer}", "=" * 70]
    for ln in t.lines:
        val = "-" if ln.value is None else (f"{ln.value:,.2f}" if isinstance(ln.value, float) else str(ln.value))
        out.append(f"{ln.step:>2}. {ln.label}: {val}")
        out.append(f"      how:    {ln.formula}")
        out.append(f"      source: {ln.source}  [{ln.status}]" + (f"  as of {ln.as_of}" if ln.as_of else ""))
    out.append("-" * 70)
    out.append(f"Verdict vs reference: {t.verdict}")
    out.append(f"Quote ready: {'YES' if t.quote_ready else 'NO'}")
    for b in t.blockers:
        out.append(f"  - {b}")
    return "\n".join(out)


def load_rows(path: str) -> List[Dict[str, Any]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        first = fh.readline()
        fh.seek(0)
        delim = "\t" if "\t" in first else ","
        return [r for r in csv.DictReader(fh, delimiter=delim) if any((v or "").strip() for v in r.values())]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    engine = RateBenchmarkEngine()
    traces = [build_trace(engine, row) for row in load_rows(sys.argv[1])]
    for tr in traces:
        print(format_trace(tr), end="\n\n")
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as fh:
            json.dump([asdict(t) for t in traces], fh, indent=2, default=str)
        print(f"Wrote {sys.argv[2]}")

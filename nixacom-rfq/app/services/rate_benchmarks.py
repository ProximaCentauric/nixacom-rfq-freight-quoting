"""
Rate Benchmark Engine - live market comparison for ocean FCL target rates.

Behaviour changes vs. the hardcoded version:
  * Market rate comes from stored lane rates (LaneRateProvider), not constants.
  * Never invents a rate: unknown lane => status UNAVAILABLE, competitiveness
    UNKNOWN. Old rates are flagged STALE instead of silently trusted.
  * Index rates are per 40' container (FEU); 20' targets are not compared.
  * Index rates already include carrier surcharges (BAF etc.), so a diesel
    surcharge is NOT added to the ocean rate by default. Inland fuel surcharge
    is opt-in (INLAND_FSC_ENABLED=true) and uses the EIA diesel price with
    YOUR company's schedule from env vars - no invented numbers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.services.rate_providers import (
    DieselReading,
    EIADieselClient,
    LaneRateProvider,
)

MAX_RATE_AGE_HOURS = float(os.getenv("RATE_MAX_AGE_HOURS", "72"))
FAIR_BAND_PCT = float(os.getenv("RATE_FAIR_BAND_PCT", "10"))


@dataclass
class RateBenchmarkResult:
    status: str  # OK | STALE | UNAVAILABLE | UNSUPPORTED_EQUIPMENT
    target_rate: float
    market_avg_rate: Optional[float]
    fuel_surcharge: float
    variance_pct: Optional[float]
    competitiveness: str  # BELOW_MARKET | FAIR | ABOVE_MARKET | UNKNOWN
    index_sources: Dict[str, Any]
    as_of: Optional[datetime] = None
    notes: list[str] = field(default_factory=list)


def _is_feu(equipment: Optional[str]) -> bool:
    if not equipment:
        return True  # caller did not say; assume 40'
    return equipment.strip().lower().startswith("40")


class RateBenchmarkEngine:
    def __init__(
        self,
        provider: Optional[LaneRateProvider] = None,
        eia: Optional[EIADieselClient] = None,
    ) -> None:
        self.provider = provider or LaneRateProvider()
        self.eia = eia or EIADieselClient()

    # ---- inland fuel surcharge (opt-in) ---------------------------------
    @staticmethod
    def _fsc_pct(diesel: DieselReading) -> float:
        """
        Standard peg/step table: +PCT_PER_STEP % for every STEP $/gal the
        diesel price is above PEG. All three come from your fuel schedule.
        """
        try:
            peg = float(os.environ["FSC_PEG_USD"])
            step = float(os.environ["FSC_STEP_USD"])
            pct_per_step = float(os.environ["FSC_PCT_PER_STEP"])
        except KeyError as missing:
            raise RuntimeError(
                f"INLAND_FSC_ENABLED is true but {missing} is not set"
            ) from None
        steps = max(0.0, (diesel.price_usd_per_gal - peg) / step)
        return round(steps * pct_per_step, 2)

    async def get_eia_fuel_surcharge(self, base_amount: float) -> Dict[str, Any]:
        diesel = await self.eia.latest()
        if diesel is None:
            return {"source": "EIA unavailable", "amount": 0.0, "pct": None}
        pct = self._fsc_pct(diesel)
        return {
            "source": diesel.source,
            "current_diesel_price_usd": diesel.price_usd_per_gal,
            "period": diesel.period,
            "pct": pct,
            "amount": round(base_amount * pct / 100.0, 2),
        }

    # ---- main entry ------------------------------------------------------
    async def evaluate_target_rate(
        self,
        db: Session,
        origin_code: str,
        dest_code: str,
        target_rate: float,
        equipment: Optional[str] = None,
    ) -> RateBenchmarkResult:
        sources: Dict[str, Any] = {}

        def unavailable(status: str, note: str) -> RateBenchmarkResult:
            return RateBenchmarkResult(
                status=status,
                target_rate=target_rate,
                market_avg_rate=None,
                fuel_surcharge=0.0,
                variance_pct=None,
                competitiveness="UNKNOWN",
                index_sources=sources,
                notes=[note],
            )

        if not _is_feu(equipment):
            return unavailable(
                "UNSUPPORTED_EQUIPMENT",
                f"Market rates are per 40' container; '{equipment}' not compared.",
            )

        lane = self.provider.get_rate(db, origin_code, dest_code)
        if lane is None:
            return unavailable(
                "UNAVAILABLE",
                f"No market rate on file for {origin_code}-{dest_code}. "
                "Load one via POST /api/rates/lanes.",
            )

        sources["base_rate_index"] = {
            "lane": lane.lane_key,
            "precision": lane.precision,
            "source": lane.source,
            "as_of": lane.as_of.isoformat(),
            "unit": "USD per 40' container",
        }

        notes: list[str] = []
        status = "OK"
        if lane.age_hours > MAX_RATE_AGE_HOURS:
            status = "STALE"
            notes.append(
                f"Market rate is {lane.age_hours / 24:.1f} days old "
                f"(limit {MAX_RATE_AGE_HOURS / 24:.1f} days) - refresh before quoting."
            )
        if lane.precision == "REGIONAL_INDEX":
            notes.append("Regional index used; no port-pair rate on file.")

        fuel_amount = 0.0
        if os.getenv("INLAND_FSC_ENABLED", "false").lower() == "true":
            fsc = await self.get_eia_fuel_surcharge(lane.rate_usd_per_feu)
            sources["fuel_index"] = fsc
            fuel_amount = fsc["amount"]

        market_total = round(lane.rate_usd_per_feu + fuel_amount, 2)
        variance = round((target_rate - market_total) / market_total * 100.0, 2)

        if variance < -FAIR_BAND_PCT:
            competitiveness = "BELOW_MARKET"
        elif variance > FAIR_BAND_PCT:
            competitiveness = "ABOVE_MARKET"
        else:
            competitiveness = "FAIR"

        return RateBenchmarkResult(
            status=status,
            target_rate=target_rate,
            market_avg_rate=market_total,
            fuel_surcharge=fuel_amount,
            variance_pct=variance,
            competitiveness=competitiveness,
            index_sources=sources,
            as_of=lane.as_of,
            notes=notes,
        )

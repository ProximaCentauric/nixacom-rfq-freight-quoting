"""
Live market-data sources for the rate benchmark engine.

1. LaneRateProvider  - newest stored market rate per lane (DB-backed). Fill the
                       table from a licensed index feed (e.g. FBX export) or
                       from real carrier/forwarder quotes.
2. EIADieselClient   - weekly U.S. on-highway diesel price from the free EIA
                       Open Data API (needs EIA_API_KEY). Used only for INLAND
                       fuel surcharges, never for the ocean leg.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.models import LaneRateModel

log = logging.getLogger(__name__)

# Port -> regional index lane. Extend as you add ports to feasibility.py.
PORT_REGION: dict[str, str] = {
    "CNSHA": "CEA",  # China / East Asia
    "CNSNZ": "CEA",
    "USLGB": "NAW",  # North America West Coast
    "USLAX": "NAW",
    "DEHAM": "NEU",  # North Europe
    "NLRTM": "NEU",
}


@dataclass
class LaneRate:
    lane_key: str
    rate_usd_per_feu: float
    as_of: datetime  # timezone-aware UTC
    source: str
    precision: str  # "PORT_PAIR" or "REGIONAL_INDEX"

    @property
    def age_hours(self) -> float:
        return (datetime.now(timezone.utc) - self.as_of).total_seconds() / 3600.0


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


class LaneRateProvider:
    """Newest stored rate for a lane; port-pair beats regional index."""

    def get_rate(self, db: Session, origin_code: str, dest_code: str) -> Optional[LaneRate]:
        o, d = origin_code.upper(), dest_code.upper()
        candidates = [(f"{o}-{d}", "PORT_PAIR")]
        if o in PORT_REGION and d in PORT_REGION:
            candidates.append((f"{PORT_REGION[o]}-{PORT_REGION[d]}", "REGIONAL_INDEX"))

        for lane_key, precision in candidates:
            row = (
                db.query(LaneRateModel)
                .filter(LaneRateModel.lane_key == lane_key)
                .order_by(LaneRateModel.as_of.desc())
                .first()
            )
            if row:
                return LaneRate(
                    lane_key=lane_key,
                    rate_usd_per_feu=row.rate_usd_per_feu,
                    as_of=_as_utc(row.as_of),
                    source=row.source,
                    precision=precision,
                )
        return None


@dataclass
class DieselReading:
    price_usd_per_gal: float
    period: str  # EIA week, e.g. "2026-11-09"
    source: str = "U.S. EIA weekly on-highway diesel (U.S. average)"


class EIADieselClient:
    """
    Calls the EIA v2 API. Cached for 6h: EIA publishes weekly, so more calls
    only burn quota. If EIA is down we serve the last good reading and the
    caller sees its true period date; with no cache at all we return None.

    NOTE: confirm the route/series below with one real call before go-live
    (see the README steps) - I could not execute it from my sandbox.
    """

    URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
    SERIES = "EMD_EPD2D_PTE_NUS_DPG"  # U.S. No 2 diesel retail, $/gal
    TTL_SECONDS = 6 * 3600

    def __init__(self) -> None:
        self._cached: Optional[DieselReading] = None
        self._cached_at: float = 0.0

    async def latest(self) -> Optional[DieselReading]:
        if self._cached and time.time() - self._cached_at < self.TTL_SECONDS:
            return self._cached

        api_key = os.getenv("EIA_API_KEY")
        if not api_key:
            log.warning("EIA_API_KEY not set; diesel index unavailable")
            return self._cached

        params = {
            "api_key": api_key,
            "frequency": "weekly",
            "data[0]": "value",
            "facets[series][]": self.SERIES,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": "1",
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(self.URL, params=params)
                resp.raise_for_status()
                row = resp.json()["response"]["data"][0]
            self._cached = DieselReading(
                price_usd_per_gal=float(row["value"]), period=str(row["period"])
            )
            self._cached_at = time.time()
        except Exception as exc:  # network, quota, schema change - never crash a quote
            log.error("EIA diesel fetch failed: %s", exc)
        return self._cached

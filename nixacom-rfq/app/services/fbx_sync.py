"""
Freightos Baltic Index (FBX) sync - PLACEHOLDER until you have API access.

Everything you need to change is marked  >>> REPLACE <<<  (3 places).
Nothing here runs unless FBX_API_KEY and FBX_API_BASE are set in .env, so it
is safe to deploy as-is: the rest of the app keeps using whatever rates are
already in the lane_rates table.

Flow: fetch_fbx_rates() -> list of lane dicts -> sync_fbx_rates() stores them
in lane_rates -> the benchmark engine picks up the newest one per lane.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models import LaneRateModel

log = logging.getLogger(__name__)


class FBXNotConfigured(Exception):
    """FBX_API_KEY / FBX_API_BASE are not set."""


# >>> REPLACE (1/3) <<<  Map Freightos' index/lane identifiers (see their API
# docs) to the regional lane keys the engine uses (see PORT_REGION in
# rate_providers.py). Example shape only - these ids are NOT verified:
FBX_LANE_MAP: dict[str, str] = {
    # "<freightos index id for China/East Asia -> NA West Coast>": "CEA-NAW",
    # "<freightos index id for China/East Asia -> N. Europe>": "CEA-NEU",
}


def _config() -> tuple[str, str]:
    key = os.getenv("FBX_API_KEY")
    base = os.getenv("FBX_API_BASE")
    if not key or not base:
        raise FBXNotConfigured("Set FBX_API_KEY and FBX_API_BASE in .env")
    return key, base.rstrip("/")


async def fetch_fbx_rates() -> list[dict[str, Any]]:
    """Return [{lane_key, rate_usd_per_feu, as_of(datetime, UTC)}, ...]."""
    key, base = _config()

    # >>> REPLACE (2/3) <<<  Request exactly as Freightos' docs describe:
    # endpoint path, auth scheme (Bearer token vs API-key header), query params.
    url = f"{base}/REPLACE_WITH_ENDPOINT_PATH"
    headers = {"Authorization": f"Bearer {key}"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        payload = resp.json()

    # >>> REPLACE (3/3) <<<  Parse their response. The field names below
    # ("data", "index", "value", "date") are placeholders.
    out: list[dict[str, Any]] = []
    for item in payload["data"]:
        lane_key = FBX_LANE_MAP.get(str(item["index"]))
        if not lane_key:
            continue  # lane we don't map; ignore
        out.append(
            {
                "lane_key": lane_key,
                "rate_usd_per_feu": float(item["value"]),
                "as_of": datetime.fromisoformat(str(item["date"]).replace("Z", "+00:00"))
                .astimezone(timezone.utc),
            }
        )
    return out


async def sync_fbx_rates(db: Session) -> dict[str, int]:
    """Store new FBX observations. Re-running is safe: duplicates are skipped."""
    rates = await fetch_fbx_rates()
    inserted = skipped = 0
    for r in rates:
        as_of_naive = r["as_of"].replace(tzinfo=None)
        exists = (
            db.query(LaneRateModel)
            .filter(
                LaneRateModel.lane_key == r["lane_key"],
                LaneRateModel.as_of == as_of_naive,
                LaneRateModel.source == "Freightos Baltic Index (FBX)",
            )
            .first()
        )
        if exists or not (0 < r["rate_usd_per_feu"] < 100000):
            skipped += 1
            continue
        db.add(
            LaneRateModel(
                lane_key=r["lane_key"],
                rate_usd_per_feu=r["rate_usd_per_feu"],
                source="Freightos Baltic Index (FBX)",
                as_of=as_of_naive,
            )
        )
        inserted += 1
    db.commit()
    log.info("FBX sync: %d inserted, %d skipped", inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}

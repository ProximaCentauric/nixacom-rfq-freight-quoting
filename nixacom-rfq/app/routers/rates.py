"""Market rate maintenance endpoints (feed the lane_rates table)."""

import hmac
import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LaneRateModel
from app.services.fbx_sync import FBXNotConfigured, sync_fbx_rates

router = APIRouter(prefix="/api/rates", tags=["rates"])


def require_admin(x_admin_key: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("RATES_ADMIN_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="RATES_ADMIN_KEY is not configured")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=401, detail="Invalid admin key")


class LaneRateIn(BaseModel):
    lane_key: str = Field(..., examples=["CNSHA-USLGB", "CEA-NAW"])
    rate_usd_per_feu: float = Field(..., gt=0, lt=100000)
    source: str = Field(..., min_length=2)
    as_of: Optional[datetime] = None  # defaults to now (UTC)


@router.post("/lanes", dependencies=[Depends(require_admin)])
async def upsert_lane_rates(rates: List[LaneRateIn], db: Session = Depends(get_db)):
    """Append observed market rates. Newest as_of per lane wins at quote time."""
    for r in rates:
        as_of = r.as_of or datetime.now(timezone.utc)
        db.add(
            LaneRateModel(
                lane_key=r.lane_key.strip().upper(),
                rate_usd_per_feu=r.rate_usd_per_feu,
                source=r.source,
                as_of=as_of.astimezone(timezone.utc).replace(tzinfo=None),
            )
        )
    db.commit()
    return {"status": "success", "inserted": len(rates)}


@router.get("/lanes")
async def list_latest_rates(db: Session = Depends(get_db)):
    """Latest stored rate per lane, so ops can see what the engine sees."""
    rows = db.query(LaneRateModel).order_by(LaneRateModel.as_of.desc()).all()
    latest = {}
    for row in rows:
        latest.setdefault(row.lane_key, row)
    return {
        "status": "success",
        "lanes": [
            {
                "lane_key": r.lane_key,
                "rate_usd_per_feu": r.rate_usd_per_feu,
                "source": r.source,
                "as_of": r.as_of.isoformat(),
            }
            for r in latest.values()
        ],
    }


@router.post("/sync/fbx", dependencies=[Depends(require_admin)])
async def sync_from_fbx(db: Session = Depends(get_db)):
    """Pull the latest Freightos Baltic Index rates into lane_rates."""
    try:
        result = await sync_fbx_rates(db)
    except FBXNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FBX sync failed: {exc}")
    return {"status": "success", **result}
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, Integer, JSON, String, Text
from app.database import Base

class RFQRecordModel(Base):
    __tablename__ = "rfq_records"

    rfq_id = Column(String, primary_key=True, index=True)
    sender = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    origin = Column(String, nullable=False)
    destination = Column(String, nullable=False)
    equipment_type = Column(String, nullable=False)
    equipment_quantity = Column(Float, nullable=False)
    target_rate_usd = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    intent_summary = Column(Text, nullable=True)
    status = Column(String, default="PENDING")
    raw_payload = Column(JSON, nullable=True)
    
    # Use lambda with timezone-aware datetime to avoid deprecation warnings
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class LaneRateModel(Base):
    """
    One observed market rate for a lane, per 40' container (FEU).

    lane_key is either a port pair ("CNSHA-USLGB", most precise) or a
    regional index lane ("CEA-NAW"). Rows are append-only: the engine always
    uses the newest as_of, and history stays available for audit/trend charts.
    """
    __tablename__ = "lane_rates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lane_key = Column(String, nullable=False, index=True)
    rate_usd_per_feu = Column(Float, nullable=False)
    source = Column(String, nullable=False)  # e.g. "FBX export", "Maersk quote #123"
    as_of = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

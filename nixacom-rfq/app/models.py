from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, String, Float, JSON, Text
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
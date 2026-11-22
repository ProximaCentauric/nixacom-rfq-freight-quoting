"""
RFQ endpoints — matches the API direction in section 18.

This is a scaffold: handlers are stubbed with clear TODOs marking
where DB queries, the extraction pipeline, and integrations plug in.
Wire up a real DB session (e.g. SQLAlchemy + asyncpg) before use.
"""

from uuid import UUID
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File
from sqlalchemy.orm import Session
from uuid import uuid4
import os
import re
import httpx

from app.database import get_db
from app.models import RFQRecordModel
from app.services.feasibility import FeasibilityEngine
from app.services.document_parser import DocumentParser
from app.services.rate_benchmarks import RateBenchmarkEngine
from app.schemas import RFQExtraction, CargoPhysicals, HazMatAndSpecial, CommercialTerms
from app.core.auth import cbp_auth
from app.services.deepseek import analyze_rfq_with_deepseek

# Safely import production validation service if available, otherwise fall back gracefully
try:
    from app.services.validation import validate_rfq
except ImportError:
    validate_rfq = None

from app.schemas import (
    RFQExtraction,
    CargoPhysicals,
    HazMatAndSpecial,
    CommercialTerms,
)


router = APIRouter(prefix="/api/rfqs", tags=["rfqs"])

_LOCODE_IN_PARENS = re.compile(r"\(([A-Za-z]{2}[A-Za-z0-9]{3})\)")
_BARE_LOCODE = re.compile(r"[A-Za-z]{2}[A-Za-z0-9]{3}")


def _extract_locode(value) -> Optional[str]:
    """'VNSGN' or 'Ho Chi Minh City, VN (VNSGN)' -> 'VNSGN'. Anything else -> None."""
    text = str(value or "").strip()
    if _BARE_LOCODE.fullmatch(text):
        return text.upper()
    match = _LOCODE_IN_PARENS.search(text)
    return match.group(1).upper() if match else None

def is_valid_rfq_email(subject: str, body_text: str) -> bool:
    """Basic keyword check to verify if an incoming email looks like an RFQ."""
    keywords = ["rfq", "quote", "rate", "freight", "container", "fcl", "lcl", "shipment"]
    combined = f"{subject} {body_text}".lower()
    return any(keyword in combined for keyword in keywords)

class ExtendedApprovalPayload(BaseModel):
    rfq_id: Optional[str] = "RFQ-TEMP-001"
    origin: Optional[str] = None
    destination: Optional[str] = None
    equipment_type: Optional[str] = None
    equipment_quantity: Optional[int] = 1
    approved_by: Optional[str] = "Operator"
    cargo_physicals: Optional[CargoPhysicals] = None
    hazmat_special: Optional[HazMatAndSpecial] = None
    commercial_terms: Optional[CommercialTerms] = None

class QuoteResponseRequest(BaseModel):
    origin: str
    destination: str
    equipment: str
    target_rate: float
    customer_email: str = ""

class RFQAnalyzeRequest(BaseModel):
    rfq_text: str

@router.post("/ingest")
async def create_rfq_from_email(payload: dict, db: Session = Depends(get_db)):
    """
    Webhook target triggered when a new email arrives. Automatically
    classifies the message, initiates extraction, and persists to PostgreSQL.
    """
    subject = payload.get("subject", "")
    body_text = payload.get("body_text", "")
    message_id = payload.get("message_id", "")
    sender = payload.get("sender", "")
    attachments = payload.get("attachments", [])

    if not is_valid_rfq_email(subject, body_text):
        return {
            "status": "SKIPPED",
            "message": "Email classified as non-RFQ inquiry.",
            "message_id": message_id
        }

    generated_rfq_id = f"RFQ-{uuid4().hex[:6].upper()}"

    # Persist initial record to PostgreSQL database
    db_record = RFQRecordModel(
        rfq_id=generated_rfq_id,
        sender=sender,
        subject=subject,
        # models.py marks these columns NOT NULL, so store empty placeholders.
        # They are NOT extracted values; status PENDING_EXTRACTION says so.
        origin="",
        destination="",
        equipment_type="",
        equipment_quantity=0.0,
        target_rate_usd=None,
        confidence_score=0.0,
        intent_summary=body_text[:250],
        status="PENDING_EXTRACTION",
        raw_payload=payload
    )
    db.add(db_record)
    db.commit()
    db.refresh(db_record)

    return {
        "status": "ACCEPTED",
        "rfq_id": generated_rfq_id,
        "message_id": message_id,
        "sender": sender,
        "subject": subject,
        "has_attachments": len(attachments) > 0,
        "message": "New RFQ email detected, queued, and saved to database."
    }


@router.get("")
async def list_rfqs(status_filter: Optional[str] = None, db: Session = Depends(get_db)):
    """Query RFQs from PostgreSQL with optional status filter."""
    query = db.query(RFQRecordModel)
    if status_filter:
        query = query.filter(RFQRecordModel.status == status_filter)
    records = query.all()
    return {"status": "success", "count": len(records), "rfqs": records}


@router.post("/approve")
async def approve_rfq_top_level(payload: ExtendedApprovalPayload, db: Session = Depends(get_db)):
    """
    Operator approval -> updates status to READY_FOR_PRICING in PostgreSQL.
    """
    db_record = db.query(RFQRecordModel).filter(RFQRecordModel.rfq_id == payload.rfq_id).first()
    if not db_record:
        raise HTTPException(status_code=404, detail=f"RFQ ID {payload.rfq_id} not found.")
    db_record.status = "APPROVED_READY_FOR_PRICING"
    db.commit()

    return {
        "status": "APPROVED",
        "message": "RFQ successfully routed to the pricing engine and updated in DB.",
        "rfq_id": payload.rfq_id,
        "details": {
            "route": f"{payload.origin} -> {payload.destination}",
            "equipment": f"{payload.equipment_quantity}x {payload.equipment_type}",
            "approved_by": payload.approved_by,
        }
    }


@router.get("/{rfq_id}")
async def get_rfq(rfq_id: str, db: Session = Depends(get_db)):
    """Fetch single RFQ from PostgreSQL."""
    db_record = db.query(RFQRecordModel).filter(RFQRecordModel.rfq_id == rfq_id).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="RFQ record not found")
    return {"status": "success", "rfq": db_record}


@router.patch("/{rfq_id}")
async def update_rfq(rfq_id: UUID, payload: dict):
    """Human edits to extracted fields. Must write to audit_logs (section 19)."""
    # TODO: for each changed field, insert an audit_logs row with
    # old_value / new_value / changed_by / timestamp
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/{rfq_id}/process")
async def process_rfq(rfq_id: UUID):
    """
    Runs classify -> group -> process documents -> extract -> normalize
    -> validate (steps 2-7 of the workflow in section 4).
    """
    # TODO: enqueue a background job (Celery) rather than running inline
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/{rfq_id}/approve")
async def approve_rfq(rfq_id: UUID):
    """Operator approval -> status READY_FOR_PRICING, then export."""
    # TODO: set status, write audit log, trigger /export
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/{rfq_id}/clarification")
async def create_clarification(rfq_id: UUID):
    """
    Generates a draft clarification email for missing fields.
    Per section 12: this must NEVER be sent automatically — draft only.
    """
    # TODO: build draft from missing_fields, insert into clarification_drafts
    raise HTTPException(status_code=501, detail="Not implemented")

@router.get("/{rfq_id}/messages")
async def get_rfq_messages(rfq_id: UUID):
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/{rfq_id}/attachments")
async def get_rfq_attachments(rfq_id: UUID):
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/{rfq_id}/extraction", response_model=Optional[RFQExtraction])
async def get_rfq_extraction(rfq_id: UUID):
    raise HTTPException(status_code=501, detail="Not implemented")

feasibility_engine = FeasibilityEngine()
@router.post("/feasibility")
async def check_feasibility(rfq_payload: dict):
    result = feasibility_engine.evaluate_rfq(rfq_payload)
    return {
        "status": "success",
        "feasibility": {
            "score": result.score,
            "verdict": result.verdict,
            "transfer_lane": result.transfer_lane,
            "reasons": result.reasons,
            "breakdown": result.score_breakdown
        }
    }

@router.post("/parse-attachment")
async def parse_attachment_file(file: UploadFile = File(...)):
    """
    Parses an uploaded attachment (PDF/Excel) and returns extracted text and tables.
    """
    file_bytes = await file.read()
    parsed_doc = DocumentParser.parse_attachment(file_bytes, file.filename)
    
    return {
        "status": "SUCCESS" if parsed_doc["has_content"] else "FAILED",
        "parsed_document": parsed_doc
    }

benchmark_engine = RateBenchmarkEngine()

@router.post("/rate-benchmark")
async def benchmark_rate(payload: dict, db: Session = Depends(get_db)):
    raw_origin = payload.get("origin_code")
    raw_destination = payload.get("destination_code")
    origin = _extract_locode(raw_origin)
    destination = _extract_locode(raw_destination)
    if not origin or not destination:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not read a 5-character port code (UN/LOCODE, e.g. VNSGN) from "
                f"origin '{raw_origin}' / destination '{raw_destination}'."
            ),
        )
    try:
        target_rate = float(payload.get("target_rate") or 0.0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="target_rate must be a number")
    if target_rate <= 0:
        raise HTTPException(status_code=422, detail="target_rate must be greater than 0")

    result = await benchmark_engine.evaluate_target_rate(
        db, origin, destination, target_rate, equipment=payload.get("equipment")
    )
    return {
        "status": "success",
        "benchmark": {
            "status": result.status,
            "target_rate": result.target_rate,
            "market_avg_rate": result.market_avg_rate,
            "fuel_surcharge": result.fuel_surcharge,
            "variance_pct": result.variance_pct,
            "competitiveness": result.competitiveness,
            "as_of": result.as_of.isoformat() if result.as_of else None,
            "notes": result.notes,
            "sources": result.index_sources,
        },
    }

@router.post("/generate-quote-response")
async def generate_quote_response(payload: QuoteResponseRequest):
    """Generates a customer-facing quote email DRAFT for human review. Nothing is sent."""

    # Interim: the only rate available here is the one in the request (target_rate).
    # Refuse a missing or zero rate instead of drafting a $0.00 quote.
    quoted_rate = payload.target_rate
    if not quoted_rate or quoted_rate <= 0:
        raise HTTPException(
            status_code=400,
            detail="No rate available. Enter an approved rate before generating a quote.",
        )

    draft_banner = "[DRAFT - confirm the rate and terms before sending, then delete this line]\n\n"

    formatted_body = (
        f"{draft_banner}"
        f"Dear Logistics Team,\n\n"
        f"Thank you for your rate request. Please find our quote below.\n\n"
        f"--------------------------------------------------\n"
        f"• Route: {payload.origin} to {payload.destination}\n"
        f"• Equipment: {payload.equipment}\n"
        f"• Rate: ${quoted_rate:,.2f} USD per container\n"
        f"--------------------------------------------------\n\n"
        f"Transit time, payment terms and quote validity will be confirmed with the final quote.\n\n"
        f"To proceed, please reply to this email and our team will follow up with next steps.\n\n"
        f"Best regards,\n"
        f"Nixacom Freight Team"
    )

    return {
        "status": "DRAFT",
        "requires_human_review": True,
        "recipient": payload.customer_email,
        "subject": f"Freight Quote: {payload.origin} to {payload.destination} ({payload.equipment})",
        "quote_email": formatted_body,
    }

@router.get("/gov-eta-lookup/{port_code}")
async def get_gov_eta_lookup(port_code: str):
    """
    Government ETA / customs status lookup. NOT IMPLEMENTED for the demo: no verified
    data source is configured, so this never returns invented customs, congestion or
    sanctions results.
    """
    raise HTTPException(
        status_code=503,
        detail="Customs/ETA lookup is not configured. No data source has been verified.",
    )


@router.post("/analyze-rfq")
async def analyze_inbound_rfq(payload: RFQAnalyzeRequest, db: Session = Depends(get_db)):
    """
    Receives raw inbound RFQ text and leverages DeepSeek to extract shipping intent.
    """
    try:
        analysis_result = await analyze_rfq_with_deepseek(payload.rfq_text)
        return {
            "status": "success",
            "data": analysis_result
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to process RFQ with AI: {str(exc)}"
        )
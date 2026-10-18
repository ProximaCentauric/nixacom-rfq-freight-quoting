"""
Strict schemas for AI extraction output.

Per section 6 of the build doc: AI output must be structured JSON, not
free-form prose, and must reject/flag values it can't confidently
determine rather than guessing.

Per section 7: every important field should retain its source
(document, page, evidence text, confidence) so a human reviewer can
see where a value came from.
"""

from datetime import date
from enum import Enum
from typing import Optional, List, Dict

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    EMAIL = "email"
    ATTACHMENT = "attachment"


class FieldSource(BaseModel):
    source_type: SourceType
    document_name: Optional[str] = None       # e.g. "Packing_List.pdf"
    page: Optional[int] = None
    cell_or_location: Optional[str] = None     # e.g. "Sheet1!B4"
    evidence_text: Optional[str] = None        # raw snippet, e.g. "Gross Weight: 12,480 KGS"
    confidence: float = Field(ge=0.0, le=1.0)


class SourcedValue(BaseModel):
    """A single extracted value plus where it came from."""
    value: Optional[str] = None
    source: Optional[FieldSource] = None


class Port(BaseModel):
    name: Optional[str] = None
    port_code: Optional[str] = None


class EquipmentLine(BaseModel):
    type: Optional[str] = None      # normalized, e.g. "40HC"
    quantity: Optional[int] = None


class ValidationOutcome(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    MISSING = "MISSING"
    CONFLICT = "CONFLICT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class FieldValidation(BaseModel):
    field_name: str
    outcome: ValidationOutcome
    detail: Optional[str] = None


# --- Extended Freight Models ---

class CargoPhysicals(BaseModel):
    gross_weight_kg: Optional[float] = Field(default=None, description="Gross weight in kilograms")
    volume_cbm: Optional[float] = Field(default=None, description="Volume in cubic meters")
    piece_count: Optional[str] = Field(default=None, description="Package or piece description (e.g. '20 Pallets')")


class HazMatAndSpecial(BaseModel):
    is_hazardous: Optional[bool] = Field(default=False, description="Whether shipment contains dangerous goods")
    un_number: Optional[str] = Field(default=None, description="UN classification number (e.g. 'UN 1993')")
    temperature_control: Optional[str] = Field(default=None, description="Temperature requirements (e.g. '-18°C (Reefer)')")


class CommercialTerms(BaseModel):
    requested_validity: Optional[date] = Field(default=None, description="Requested quote validity deadline")
    target_rate_usd: Optional[float] = Field(default=None, description="Target rate in USD")
    payment_terms: Optional[str] = Field(default=None, description="Payment credit terms (e.g. 'Net 30')")


class RFQExtraction(BaseModel):
    """
    The strict schema the extraction layer must populate for an
    Ocean FCL RFQ. Mirrors the example JSON in section 5 and the
    required-field list in section 6/9.
    """

    transport_mode: str = "OCEAN"
    shipment_type: str = "FCL"

    origin: Optional[Port] = None
    destination: Optional[Port] = None

    equipment: List[EquipmentLine] = Field(default_factory=list)

    weight_kg: Optional[float] = None
    volume_cbm: Optional[float] = None

    packages: Optional[int] = None
    package_type: Optional[str] = None

    commodity: Optional[str] = None

    incoterm: Optional[str] = None
    incoterm_location: Optional[str] = None

    cargo_ready_date: Optional[date] = None

    dangerous_goods: Optional[bool] = None
    special_requirements: Optional[str] = None
    delivery_address: Optional[str] = None

    # Structured Extended Freight Information Groups
    cargo_physicals: Optional[CargoPhysicals] = Field(default_factory=CargoPhysicals)
    hazmat_special: Optional[HazMatAndSpecial] = Field(default_factory=HazMatAndSpecial)
    commercial_terms: Optional[CommercialTerms] = Field(default_factory=CommercialTerms)

    # Traceability: field_name -> source info
    field_sources: Dict[str, FieldSource] = Field(default_factory=dict)

    # Fields the model could not confidently determine
    missing_fields: List[str] = Field(default_factory=list)

    # Fields where two sources disagreed (never silently resolved)
    conflicting_fields: Dict[str, List[SourcedValue]] = Field(default_factory=dict)

    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


REQUIRED_FIELDS = [
    "origin",
    "destination",
    "equipment",
    "cargo_ready_date",
    "incoterm",
]

CONDITIONAL_FIELDS = [
    "commodity",
    "weight_kg",
    "volume_cbm",
    "delivery_address",
    "dangerous_goods",
    "cargo_physicals",
    "hazmat_special",
    "commercial_terms",
]

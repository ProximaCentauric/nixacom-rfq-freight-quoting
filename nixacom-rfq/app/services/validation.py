"""
Deterministic validation engine.

Per section 9: use AI for understanding messy input, but use
deterministic rules for validation — never let the model decide
pass/fail on its own.

Per section 10: if two sources disagree, surface the conflict; never
let the AI silently pick one.
"""

from app.schemas import (
    CONDITIONAL_FIELDS,
    REQUIRED_FIELDS,
    FieldValidation,
    RFQExtraction,
    ValidationOutcome,
)


def validate_extraction(extraction: RFQExtraction) -> list[FieldValidation]:
    results: list[FieldValidation] = []

    # Required fields
    for field_name in REQUIRED_FIELDS:
        value = getattr(extraction, field_name, None)
        if not value:
            results.append(
                FieldValidation(
                    field_name=field_name,
                    outcome=ValidationOutcome.MISSING,
                    detail=f"'{field_name}' is required for Ocean FCL pricing.",
                )
            )
        else:
            results.append(
                FieldValidation(field_name=field_name, outcome=ValidationOutcome.PASS)
            )

    # Conditionally required fields -> WARNING rather than MISSING
    for field_name in CONDITIONAL_FIELDS:
        value = getattr(extraction, field_name, None)
        if value in (None, ""):
            results.append(
                FieldValidation(
                    field_name=field_name,
                    outcome=ValidationOutcome.WARNING,
                    detail=f"'{field_name}' not found; confirm if relevant to this shipment.",
                )
            )
        else:
            results.append(
                FieldValidation(field_name=field_name, outcome=ValidationOutcome.PASS)
            )

    # Conflicts detected during extraction (e.g. equipment qty differs
    # between email and packing list) always require human confirmation.
    for field_name in extraction.conflicting_fields:
        results.append(
            FieldValidation(
                field_name=field_name,
                outcome=ValidationOutcome.CONFLICT,
                detail="Sources disagree; human confirmation required.",
            )
        )

    return results


def compute_overall_status(validations: list[FieldValidation]) -> str:
    """Map validation results to an RFQ status (section 13)."""
    outcomes = {v.outcome for v in validations}

    if ValidationOutcome.CONFLICT in outcomes:
        return "NEEDS_REVIEW"
    if ValidationOutcome.MISSING in outcomes:
        return "NEEDS_CUSTOMER_INFO"
    if ValidationOutcome.WARNING in outcomes or ValidationOutcome.REVIEW_REQUIRED in outcomes:
        return "NEEDS_REVIEW"
    return "READY_FOR_PRICING"

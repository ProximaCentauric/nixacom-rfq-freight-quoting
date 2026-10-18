"""Integration endpoints — Outlook connection/webhook, generic export."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.post("/outlook/connect")
async def outlook_connect(payload: dict):
    """
    OAuth handoff for Microsoft Graph. Store tokens via a secret
    manager reference (never raw tokens) in `email_accounts`.
    """
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/outlook/webhook")
async def outlook_webhook(request: Request):
    """
    Microsoft Graph change notification endpoint. On a new message
    notification: fetch the message, group by conversationId, enqueue
    classification (step 1-3 of the workflow in section 4).
    """
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/{integration_id}/export")
async def export_rfq(integration_id: UUID, payload: dict):
    """Send a READY_FOR_PRICING RFQ's structured data to a webhook/TMS."""
    raise HTTPException(status_code=501, detail="Not implemented")

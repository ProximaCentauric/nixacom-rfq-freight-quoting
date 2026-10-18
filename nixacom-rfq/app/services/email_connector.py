"""
Email connector service for automatically detecting and fetching incoming RFQs.
Supports IMAP polling and payload transformation for backend processing.
"""

import email
import imaplib
from email.header import decode_header
from typing import Dict, Any, List, Optional
import re


def decode_str(header_value: Any) -> str:
    """Helper function to decode email headers into plain UTF-8 strings."""
    if not header_value:
        return ""
    decoded_fragments = decode_header(header_value)
    result = []
    for fragment, encoding in decoded_fragments:
        if isinstance(fragment, bytes):
            result.append(fragment.decode(encoding or "utf-8", errors="replace"))
        else:
            result.append(str(fragment))
    return "".join(result)


def is_valid_rfq_email(subject: str, body: str) -> bool:
    """
    Basic heuristic filter to detect if an incoming email is a valid RFQ inquiry
    rather than spam, standard newsletter, or out-of-office automated response.
    """
    combined_text = f"{subject} {body}".lower()

    # Reject standard automated/out-of-office subject triggers
    auto_reply_keywords = ["out of office", "automatic reply", "undeliverable", "delivery status notification"]
    if any(keyword in combined_text for keyword in auto_reply_keywords):
        return False

    # Standard freight keywords indicating an RFQ inquiry
    rfq_keywords = [
        "quote", "rfq", "rate", "inquiry", "container", "fcl", "lcl",
        "freight", "shipment", "ocean", "port", "pol", "pod", "incoterm"
    ]
    
    # Needs at least one freight keyword to pass initial filter
    return any(keyword in combined_text for keyword in rfq_keywords)


def parse_raw_email(raw_bytes: bytes) -> Dict[str, Any]:
    """Parses raw email bytes into structured metadata and body text."""
    msg = email.message_from_bytes(raw_bytes)

    subject = decode_str(msg.get("Subject"))
    sender = decode_str(msg.get("From"))
    message_id = msg.get("Message-ID", "")
    date_sent = msg.get("Date", "")

    body_text = ""
    attachments_meta = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            # Extract body text
            if content_type == "text/plain" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    body_text += payload.decode("utf-8", errors="replace")
            # Track attachments
            elif "attachment" in content_disposition or part.get_filename():
                filename = decode_str(part.get_filename())
                if filename:
                    attachments_meta.append({
                        "filename": filename,
                        "content_type": content_type,
                        "size_bytes": len(part.get_payload(decode=True) or b"")
                    })
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body_text = payload.decode("utf-8", errors="replace")

    return {
        "message_id": message_id,
        "sender": sender,
        "subject": subject,
        "date_sent": date_sent,
        "body_text": body_text.strip(),
        "attachments": attachments_meta,
        "is_rfq": is_valid_rfq_email(subject, body_text)
    }


class IMAPEmailPoller:
    """IMAP client to continuously check an inbox for unseen emails."""

    def __init__(self, host: str, user: str, pass_code: str, mailbox: str = "INBOX"):
        self.host = host
        self.user = user
        self.pass_code = pass_code
        self.mailbox = mailbox

    def fetch_unseen_rfqs(self) -> List[Dict[str, Any]]:
        """Connects to mailbox, searches for UNSEEN emails, parses and returns valid RFQs."""
        rfq_emails = []
        try:
            mail = imaplib.IMAP4_SSL(self.host)
            mail.login(self.user, self.pass_code)
            mail.select(self.mailbox)

            # Search for unread emails
            status, response = mail.search(None, "UNSEEN")
            if status != "OK" or not response[0]:
                mail.logout()
                return []

            email_ids = response[0].split()

            for e_id in email_ids:
                res_status, msg_data = mail.fetch(e_id, "(RFC822)")
                if res_status != "OK":
                    continue

                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        parsed_email = parse_raw_email(response_part[1])
                        if parsed_email["is_rfq"]:
                            rfq_emails.append(parsed_email)

            mail.logout()
        except Exception as err:
            print(f"[IMAP Connector Error] Failed to fetch emails: {err}")

        return rfq_emails
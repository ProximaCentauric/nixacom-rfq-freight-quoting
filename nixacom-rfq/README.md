# Nixacom RFQ Automation — Scaffold

Initial scaffold matching the build doc's suggested architecture (section 15/16).

## What's here

```
db/schema.sql              Postgres schema (section 17 entities)
app/main.py                FastAPI entrypoint
app/schemas.py             Strict Pydantic schema for AI extraction output (section 6/7)
app/routers/rfqs.py        RFQ endpoints (section 18) — stubbed, ready to wire to DB
app/routers/integrations.py Outlook connect/webhook + export endpoints
app/services/validation.py Deterministic validation engine (section 9/10)
app/services/normalization.py Deterministic normalization tables (section 8)
requirements.txt
```

## What's NOT built yet (by design — this is a starting scaffold)

- Database connection layer (SQLAlchemy models + session, Alembic migrations)
- The actual AI extraction call (Anthropic API + prompt + JSON schema enforcement)
- Document processing (PDF/XLSX parsing, OCR)
- Microsoft Graph OAuth flow + webhook signature validation
- Celery task definitions for the async pipeline
- Auth / RBAC middleware
- The review dashboard frontend

## Suggested build order

1. **DB first**: stand up Postgres (Supabase is fastest), run `db/schema.sql`, add SQLAlchemy models matching it.
2. **Extraction in isolation**: write a script that takes the example email from section 5, calls Claude with a prompt that forces output into `RFQExtraction`, and check it against the expected JSON. Get this right before wiring anything else — it's the core of the product.
3. **Wire `/rfqs/{id}/process`**: connect extraction + `normalization.py` + `validation.py` into the stubbed endpoint, backed by a Celery task so it doesn't block.
4. **Outlook ingestion**: Microsoft Graph subscription → webhook → create RFQ → enqueue processing.
5. **Review dashboard**: minimal Next.js page hitting `GET /api/rfqs/{id}` and `PATCH` for edits.

## Local setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# once you have a Postgres URL:
psql $DATABASE_URL -f db/schema.sql

uvicorn app.main:app --reload
```

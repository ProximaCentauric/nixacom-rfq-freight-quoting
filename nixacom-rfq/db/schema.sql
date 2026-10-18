-- Nixacom RFQ Automation — initial schema
-- Matches the entity list and relationships in section 17 of the build doc.
-- Target: PostgreSQL (Supabase-compatible)

create extension if not exists "uuid-ossp";

-- ─────────────────────────────────────────────
-- Core tenancy
-- ─────────────────────────────────────────────

create table organizations (
    id uuid primary key default uuid_generate_v4(),
    name text not null,
    created_at timestamptz not null default now()
);

create table users (
    id uuid primary key default uuid_generate_v4(),
    organization_id uuid not null references organizations(id) on delete cascade,
    email text not null unique,
    full_name text,
    role text not null default 'operator', -- operator | admin | viewer
    created_at timestamptz not null default now()
);

-- ─────────────────────────────────────────────
-- Email ingestion
-- ─────────────────────────────────────────────

create table email_accounts (
    id uuid primary key default uuid_generate_v4(),
    organization_id uuid not null references organizations(id) on delete cascade,
    provider text not null default 'outlook', -- outlook | gmail
    mailbox_address text not null,
    access_token_ref text, -- pointer into secret manager, never raw token
    refresh_token_ref text,
    connected_at timestamptz,
    created_at timestamptz not null default now()
);

create table email_threads (
    id uuid primary key default uuid_generate_v4(),
    email_account_id uuid not null references email_accounts(id) on delete cascade,
    provider_thread_id text not null, -- Outlook conversationId
    subject text,
    created_at timestamptz not null default now(),
    unique (email_account_id, provider_thread_id)
);

create table email_messages (
    id uuid primary key default uuid_generate_v4(),
    email_thread_id uuid not null references email_threads(id) on delete cascade,
    provider_message_id text not null,   -- Message-ID
    in_reply_to text,
    references_header text,
    from_address text,
    to_addresses text[],
    sent_at timestamptz,
    body_text text,
    classification text, -- new_rfq | follow_up | clarification | booking | invoice | general
    created_at timestamptz not null default now()
);

create table attachments (
    id uuid primary key default uuid_generate_v4(),
    email_message_id uuid not null references email_messages(id) on delete cascade,
    filename text not null,
    content_type text,
    storage_key text not null, -- S3-compatible object key
    document_type text,        -- packing_list | booking_confirmation | other
    page_count int,
    ocr_used boolean not null default false,
    created_at timestamptz not null default now()
);

-- ─────────────────────────────────────────────
-- Customers & RFQs
-- ─────────────────────────────────────────────

create table customers (
    id uuid primary key default uuid_generate_v4(),
    organization_id uuid not null references organizations(id) on delete cascade,
    name text not null,
    primary_contact_email text,
    created_at timestamptz not null default now()
);

create table rfqs (
    id uuid primary key default uuid_generate_v4(),
    organization_id uuid not null references organizations(id) on delete cascade,
    customer_id uuid references customers(id),
    email_thread_id uuid references email_threads(id),
    display_ref text, -- e.g. "RFQ #10482"
    status text not null default 'RECEIVED',
        -- RECEIVED | PROCESSING | EXTRACTED | NEEDS_REVIEW | NEEDS_CUSTOMER_INFO
        -- READY_FOR_PRICING | PRICING_IN_PROGRESS | QUOTED | CLOSED | ERROR
    transport_mode text default 'OCEAN',
    shipment_type text default 'FCL',
    ai_confidence numeric(4,3), -- overall confidence, 0.000–1.000
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- One row per extracted field on an RFQ (origin, destination, weight, etc.)
create table rfq_fields (
    id uuid primary key default uuid_generate_v4(),
    rfq_id uuid not null references rfqs(id) on delete cascade,
    field_name text not null,   -- e.g. "weight_kg", "origin_port_code"
    field_value text,           -- normalized value, stored as text/JSON-castable
    normalized boolean not null default false,
    confidence numeric(4,3),
    is_required boolean not null default false,
    created_at timestamptz not null default now(),
    unique (rfq_id, field_name)
);

-- Where each field value came from (traceability — section 7)
create table rfq_field_sources (
    id uuid primary key default uuid_generate_v4(),
    rfq_field_id uuid not null references rfq_fields(id) on delete cascade,
    source_type text not null, -- email | attachment
    email_message_id uuid references email_messages(id),
    attachment_id uuid references attachments(id),
    page_number int,
    cell_or_location text,     -- e.g. worksheet/cell ref for XLSX
    evidence_text text,        -- raw snippet supporting the value
    created_at timestamptz not null default now()
);

create table rfq_validation_results (
    id uuid primary key default uuid_generate_v4(),
    rfq_id uuid not null references rfqs(id) on delete cascade,
    field_name text not null,
    outcome text not null, -- PASS | WARNING | MISSING | CONFLICT | REVIEW_REQUIRED
    detail text,
    created_at timestamptz not null default now()
);

create table clarification_drafts (
    id uuid primary key default uuid_generate_v4(),
    rfq_id uuid not null references rfqs(id) on delete cascade,
    missing_fields text[],
    draft_body text not null,
    status text not null default 'DRAFT', -- DRAFT | EDITED | SENT
    sent_at timestamptz,
    created_at timestamptz not null default now()
);

-- ─────────────────────────────────────────────
-- Audit & integrations
-- ─────────────────────────────────────────────

create table audit_logs (
    id uuid primary key default uuid_generate_v4(),
    rfq_id uuid references rfqs(id) on delete cascade,
    user_id uuid references users(id),
    field_name text,
    old_value text,
    new_value text,
    action text not null, -- field_edit | approve | clarification_sent | export | status_change
    created_at timestamptz not null default now()
);

create table integrations (
    id uuid primary key default uuid_generate_v4(),
    organization_id uuid not null references organizations(id) on delete cascade,
    type text not null, -- webhook | tms | spreadsheet
    config jsonb not null default '{}',
    active boolean not null default true,
    created_at timestamptz not null default now()
);

create table integration_logs (
    id uuid primary key default uuid_generate_v4(),
    integration_id uuid not null references integrations(id) on delete cascade,
    rfq_id uuid references rfqs(id),
    status text not null, -- success | failure
    response_summary text,
    created_at timestamptz not null default now()
);

-- ─────────────────────────────────────────────
-- Indexes for common lookups
-- ─────────────────────────────────────────────

create index idx_rfqs_org_status on rfqs(organization_id, status);
create index idx_email_messages_thread on email_messages(email_thread_id);
create index idx_attachments_message on attachments(email_message_id);
create index idx_rfq_fields_rfq on rfq_fields(rfq_id);
create index idx_audit_logs_rfq on audit_logs(rfq_id);

ALTER TABLE conversation_memory_facts
    ADD COLUMN version bigint NOT NULL DEFAULT 0
        CHECK (version >= 0),
    ADD COLUMN deleted_at timestamptz,
    ADD CONSTRAINT conversation_memory_facts_deleted_content_check CHECK (
        deleted_at IS NULL OR (key = '' AND value = '')
    );

CREATE TABLE conversation_memory_fact_audit (
    ordinal bigserial PRIMARY KEY,
    fact_id varchar(200) NOT NULL,
    owner_id varchar(200) NOT NULL,
    version bigint NOT NULL CHECK (version >= 0),
    action varchar(16) NOT NULL,
    value_digest char(64) NOT NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT conversation_memory_fact_audit_action_check CHECK (
        action IN ('created', 'corrected', 'deleted')
    ),
    CONSTRAINT conversation_memory_fact_audit_version_unique UNIQUE (
        fact_id,
        version
    )
);

CREATE INDEX conversation_memory_fact_audit_owner_idx
    ON conversation_memory_fact_audit (owner_id, fact_id, ordinal);

INSERT INTO conversation_memory_fact_audit (
    fact_id,
    owner_id,
    version,
    action,
    value_digest,
    created_at
)
SELECT
    id,
    owner_id,
    version,
    'created',
    encode(
        sha256(
            convert_to(
                'memory-fact-value-v1:'
                    || octet_length(convert_to(value, 'UTF8'))::text
                    || ':'
                    || value,
                'UTF8'
            )
        ),
        'hex'
    ),
    created_at
FROM conversation_memory_facts;

CREATE OR REPLACE FUNCTION reject_memory_fact_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'memory fact audit is append-only';
END;
$$;

CREATE TRIGGER conversation_memory_fact_audit_append_only_trigger
BEFORE UPDATE OR DELETE ON conversation_memory_fact_audit
FOR EACH ROW
EXECUTE FUNCTION reject_memory_fact_audit_mutation();

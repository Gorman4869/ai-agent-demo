CREATE TABLE tool_approval_requests (
    id varchar(200) PRIMARY KEY,
    run_id varchar(200) NOT NULL,
    principal_id varchar(200) NOT NULL,
    tool_call_id varchar(200) NOT NULL,
    tool_name varchar(200) NOT NULL,
    arguments_digest char(64) NOT NULL,
    arguments jsonb NOT NULL CHECK (jsonb_typeof(arguments) = 'object'),
    expires_at timestamptz,
    response varchar(16),
    resolution_status varchar(16),
    created_at timestamptz NOT NULL,
    resolved_at timestamptz,
    CONSTRAINT tool_approval_requests_response_check CHECK (
        response IS NULL OR response IN ('approve', 'reject')
    ),
    CONSTRAINT tool_approval_requests_status_check CHECK (
        resolution_status IS NULL
        OR resolution_status IN ('approved', 'rejected', 'expired')
    ),
    CONSTRAINT tool_approval_requests_resolution_check CHECK (
        (response IS NULL AND resolution_status IS NULL AND resolved_at IS NULL)
        OR
        (response IS NOT NULL AND resolution_status IS NOT NULL AND resolved_at IS NOT NULL)
    ),
    CONSTRAINT tool_approval_requests_binding_unique UNIQUE (
        run_id,
        principal_id,
        tool_call_id,
        tool_name,
        arguments_digest
    )
);

CREATE INDEX tool_approval_requests_owner_idx
    ON tool_approval_requests (principal_id, run_id, created_at, id);

CREATE TABLE tool_approval_grants (
    id varchar(200) PRIMARY KEY,
    principal_id varchar(200) NOT NULL,
    run_id varchar(200) NOT NULL,
    tool_call_id varchar(200) NOT NULL,
    tool_name varchar(200) NOT NULL,
    arguments_digest char(64) NOT NULL,
    expires_at timestamptz,
    consumed_at timestamptz,
    created_at timestamptz NOT NULL,
    CONSTRAINT tool_approval_grants_binding_unique UNIQUE (
        principal_id,
        run_id,
        tool_call_id,
        tool_name,
        arguments_digest
    )
);

CREATE TABLE memory_message_sequences (
    session_id varchar(200) PRIMARY KEY,
    next_sequence bigint NOT NULL CHECK (next_sequence > 0)
);

CREATE TABLE conversation_messages (
    session_id varchar(200) NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    role varchar(16) NOT NULL,
    content text NOT NULL,
    name varchar(200),
    tool_call_id varchar(200),
    PRIMARY KEY (session_id, sequence),
    CONSTRAINT conversation_messages_role_check CHECK (
        role IN ('system', 'user', 'assistant', 'tool')
    )
);

CREATE TABLE conversation_memory_facts (
    ordinal bigserial UNIQUE,
    id varchar(200) PRIMARY KEY,
    owner_id varchar(200) NOT NULL,
    key text NOT NULL,
    value text NOT NULL,
    scope varchar(16) NOT NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT conversation_memory_facts_scope_check CHECK (
        scope IN ('session', 'user')
    )
);

CREATE INDEX conversation_memory_facts_owner_idx
    ON conversation_memory_facts (owner_id, ordinal);

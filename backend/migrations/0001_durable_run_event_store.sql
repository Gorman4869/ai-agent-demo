CREATE TABLE agent_runs (
    id varchar(200) PRIMARY KEY,
    session_id varchar(200) NOT NULL,
    owner_id varchar(200) NOT NULL,
    runtime varchar(32) NOT NULL,
    model_provider varchar(32) NOT NULL,
    model varchar(200) NOT NULL,
    input_text text NOT NULL,
    idempotency_key_digest char(64) NOT NULL,
    request_digest char(64) NOT NULL,
    status varchar(32) NOT NULL,
    version bigint NOT NULL CHECK (version >= 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    started_at timestamptz,
    finished_at timestamptz,
    answer text,
    failure_code varchar(100),
    failure_category varchar(100),
    failure_message text,
    failure_retryable boolean,
    failure_internal_ref varchar(200),
    failure_step integer CHECK (failure_step IS NULL OR failure_step >= 0),
    CONSTRAINT agent_runs_status_check CHECK (
        status IN (
            'queued',
            'running',
            'waiting_approval',
            'completed',
            'failed',
            'cancelled'
        )
    ),
    CONSTRAINT agent_runs_idempotency_unique UNIQUE (
        owner_id,
        idempotency_key_digest
    )
);

CREATE INDEX agent_runs_owner_session_created_idx
    ON agent_runs (owner_id, session_id, created_at, id);

CREATE TABLE agent_run_event_sequences (
    run_id varchar(200) PRIMARY KEY
        REFERENCES agent_runs(id) ON DELETE CASCADE,
    next_sequence bigint NOT NULL CHECK (next_sequence > 0)
);

CREATE TABLE agent_run_events (
    run_id varchar(200) NOT NULL
        REFERENCES agent_runs(id) ON DELETE CASCADE,
    sequence bigint NOT NULL CHECK (sequence > 0),
    id varchar(200) NOT NULL,
    type varchar(200) NOT NULL,
    data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object'),
    step integer NOT NULL CHECK (step >= 0),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (run_id, sequence),
    CONSTRAINT agent_run_events_id_unique UNIQUE (run_id, id)
);

CREATE INDEX agent_run_events_replay_idx
    ON agent_run_events (run_id, sequence);

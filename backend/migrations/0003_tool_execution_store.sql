CREATE TABLE tool_executions (
    id varchar(200) PRIMARY KEY,
    run_id varchar(200) NOT NULL
        REFERENCES agent_runs(id) ON DELETE CASCADE,
    tool_call_id varchar(200) NOT NULL,
    tool_name varchar(200) NOT NULL,
    arguments_digest char(64) NOT NULL,
    idempotency_key_digest char(64),
    side_effecting boolean NOT NULL,
    status varchar(32) NOT NULL,
    version bigint NOT NULL CHECK (version >= 0),
    attempt integer NOT NULL CHECK (attempt > 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    started_at timestamptz,
    finished_at timestamptz,
    result_digest char(64),
    result_summary text,
    error_code varchar(100),
    public_message text,
    CONSTRAINT tool_executions_call_unique UNIQUE (run_id, tool_call_id),
    CONSTRAINT tool_executions_status_check CHECK (
        status IN (
            'pending',
            'waiting_approval',
            'running',
            'completed',
            'failed',
            'cancelled',
            'unknown'
        )
    ),
    CONSTRAINT tool_executions_side_effect_key_check CHECK (
        NOT side_effecting OR idempotency_key_digest IS NOT NULL
    ),
    CONSTRAINT tool_executions_status_version_check CHECK (
        (status = 'pending' AND version = 0)
        OR (status <> 'pending' AND version > 0)
    ),
    CONSTRAINT tool_executions_started_check CHECK (
        (status IN ('pending', 'waiting_approval') AND started_at IS NULL)
        OR (status IN ('running', 'completed', 'unknown') AND started_at IS NOT NULL)
        OR status IN ('failed', 'cancelled')
    ),
    CONSTRAINT tool_executions_finished_check CHECK (
        (
            status IN ('completed', 'failed', 'cancelled', 'unknown')
            AND finished_at IS NOT NULL
        )
        OR (
            status IN ('pending', 'waiting_approval', 'running')
            AND finished_at IS NULL
        )
    ),
    CONSTRAINT tool_executions_outcome_check CHECK (
        (
            status = 'completed'
            AND result_digest IS NOT NULL
            AND result_summary IS NOT NULL
            AND error_code IS NULL
            AND public_message IS NULL
        )
        OR (
            status IN ('failed', 'cancelled', 'unknown')
            AND result_digest IS NULL
            AND result_summary IS NULL
            AND error_code IS NOT NULL
        )
        OR (
            status IN ('pending', 'waiting_approval', 'running')
            AND result_digest IS NULL
            AND result_summary IS NULL
            AND error_code IS NULL
            AND public_message IS NULL
        )
    ),
    CONSTRAINT tool_executions_time_check CHECK (
        updated_at >= created_at
        AND (started_at IS NULL OR started_at >= created_at)
        AND (finished_at IS NULL OR finished_at >= created_at)
        AND (
            started_at IS NULL
            OR finished_at IS NULL
            OR finished_at >= started_at
        )
    )
);

CREATE UNIQUE INDEX tool_executions_idempotency_unique
    ON tool_executions (run_id, tool_name, idempotency_key_digest)
    WHERE idempotency_key_digest IS NOT NULL;

CREATE INDEX tool_executions_run_created_idx
    ON tool_executions (run_id, created_at, id);

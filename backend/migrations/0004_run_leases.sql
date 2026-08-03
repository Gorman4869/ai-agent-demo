CREATE TABLE agent_run_leases (
    run_id varchar(200) PRIMARY KEY
        REFERENCES agent_runs(id) ON DELETE CASCADE,
    mode varchar(16) NOT NULL,
    lease_token_digest char(64) NOT NULL,
    version bigint NOT NULL CHECK (version >= 0),
    acquired_at timestamptz NOT NULL,
    heartbeat_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    CONSTRAINT agent_run_leases_mode_check CHECK (
        mode IN ('execution', 'recovery')
    ),
    CONSTRAINT agent_run_leases_time_check CHECK (
        heartbeat_at >= acquired_at
        AND expires_at > heartbeat_at
    )
);

CREATE INDEX agent_run_leases_expiry_idx
    ON agent_run_leases (expires_at, run_id);

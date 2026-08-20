CREATE TABLE conversation_turn_publications (
    run_id varchar(200) PRIMARY KEY,
    session_id varchar(200) NOT NULL,
    turn_digest char(64) NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE INDEX conversation_turn_publications_session_idx
    ON conversation_turn_publications (session_id, created_at, run_id);

CREATE TABLE review_run_requests (
    run_id varchar(200) PRIMARY KEY REFERENCES agent_runs(id) ON DELETE CASCADE,
    scenario_version varchar(32) NOT NULL CHECK (scenario_version = 'multisource-review-v1'),
    request_digest char(64) NOT NULL,
    review_id varchar(128) NOT NULL,
    expected_revision bigint NOT NULL CHECK (expected_revision > 0),
    image_asset_id varchar(64) NOT NULL,
    policy_topic text NOT NULL CHECK (octet_length(policy_topic) BETWEEN 1 AND 512),
    page_fixture_id varchar(64) NOT NULL,
    requested_decision varchar(32) NOT NULL CHECK (
        requested_decision IN ('approve', 'reject', 'needs_review')
    )
);

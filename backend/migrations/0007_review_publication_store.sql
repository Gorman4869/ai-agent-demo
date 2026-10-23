CREATE TABLE review_publication_heads (
    owner_scope_digest char(64) NOT NULL,
    review_id varchar(128) NOT NULL,
    current_revision bigint NOT NULL CHECK (current_revision > 0),
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (owner_scope_digest, review_id)
);

CREATE TABLE review_publications (
    publication_id varchar(128) PRIMARY KEY,
    owner_scope_digest char(64) NOT NULL,
    review_id varchar(128) NOT NULL,
    expected_revision bigint NOT NULL CHECK (expected_revision > 0),
    revision bigint NOT NULL CHECK (revision = expected_revision + 1),
    requested_decision varchar(32) NOT NULL,
    evidence_bundle_digest char(64) NOT NULL,
    idempotency_key_digest char(64) NOT NULL,
    binding_digest char(64) NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'published',
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT review_publications_head_fk
        FOREIGN KEY (owner_scope_digest, review_id)
        REFERENCES review_publication_heads (owner_scope_digest, review_id),
    CONSTRAINT review_publications_decision_check CHECK (
        requested_decision IN ('approve', 'reject', 'needs_review')
    ),
    CONSTRAINT review_publications_status_check CHECK (status = 'published'),
    CONSTRAINT review_publications_business_key_unique UNIQUE (
        owner_scope_digest,
        idempotency_key_digest
    ),
    CONSTRAINT review_publications_revision_unique UNIQUE (
        owner_scope_digest,
        review_id,
        expected_revision
    )
);

CREATE INDEX review_publications_review_revision_idx
    ON review_publications (owner_scope_digest, review_id, revision);

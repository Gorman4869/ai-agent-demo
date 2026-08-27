CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE dashscope_knowledge_documents (
    id varchar(200) PRIMARY KEY,
    title text NOT NULL CHECK (title <> ''),
    source text NOT NULL CHECK (source <> ''),
    content_digest char(64) NOT NULL,
    chunk_count integer NOT NULL CHECK (chunk_count > 0),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE dashscope_knowledge_chunks (
    document_id varchar(200) NOT NULL
        REFERENCES dashscope_knowledge_documents(id) ON DELETE CASCADE,
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    excerpt text NOT NULL CHECK (excerpt <> ''),
    embedding vector(64) NOT NULL,
    PRIMARY KEY (document_id, chunk_index)
);

CREATE INDEX dashscope_knowledge_chunks_embedding_hnsw_idx
    ON dashscope_knowledge_chunks
    USING hnsw (embedding vector_cosine_ops);

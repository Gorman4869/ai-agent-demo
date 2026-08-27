from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from typing import Sequence

from backend.app.evals.rag_retrieval import (
    RagRetrievalEvalReport,
    RagRetrievalEvaluator,
    load_rag_retrieval_dataset,
)
from backend.app.knowledge import (
    BatchingEmbeddingModel,
    EmbeddingMetadata,
    EmbeddingProvider,
    PGVECTOR_DIMENSIONS,
    PgVectorKnowledgeBase,
    create_psycopg_connection_factory,
)


_TERM_PATTERN = re.compile(r"[a-z0-9_@.-]+|[\u4e00-\u9fff]+")
_EVALUATION_DSN_ENVIRONMENT = "AI_AGENT_TEST_PGVECTOR_DSN"


@dataclass(frozen=True)
class _CourseTopic:
    terms: tuple[str, ...]
    vector: tuple[float, float, float]


_COURSE_TOPICS = (
    _CourseTopic(
        terms=(
            "agent loop",
            "agent",
            "模型决策",
            "工具执行",
            "循环控制",
            "最大步数",
            "最终回答",
            "继续决策",
            "工具参数",
            "参数",
            "校验",
        ),
        vector=(1.0, 0.0, 0.0),
    ),
    _CourseTopic(
        terms=(
            "身份",
            "角色",
            "授权",
            "高风险",
            "副作用",
            "handler",
            "参数校验",
            "工具请求",
            "模型参数",
            "审批",
        ),
        vector=(0.809017, 0.587785, 0.0),
    ),
    _CourseTopic(
        terms=(
            "mcp",
            "initialize",
            "stdio",
            "资源服务器",
            "客户端",
            "生命周期",
            "资源清理",
            "发现工具",
            "工具发现",
            "策略",
            "映射",
        ),
        vector=(0.309017, 0.951057, 0.0),
    ),
    _CourseTopic(
        terms=(
            "rag",
            "检索",
            "证据",
            "引用",
            "recall",
            "mrr",
            "依据正确率",
            "召回",
        ),
        vector=(-0.309017, 0.951057, 0.0),
    ),
    _CourseTopic(
        terms=(
            "长期事实",
            "持久记忆",
            "expected version",
            "cas",
            "tombstone",
            "审计",
            "清空原值",
            "删除",
            "事实",
            "不再注入",
        ),
        vector=(-0.809017, 0.587785, 0.0),
    ),
    _CourseTopic(
        terms=(
            "langgraph",
            "checkpoint",
            "工作流",
            "owner",
            "thread",
            "schema version",
            "自动重放",
            "未知结果",
        ),
        vector=(-1.0, 0.0, 0.0),
    ),
    _CourseTopic(
        terms=(
            "waiting_approval",
            "approve",
            "reject",
            "grant",
            "resume",
            "审批请求",
            "工具调用",
            "参数摘要",
            "runtime",
            "等待审批",
            "状态",
            "服务端",
            "决定",
        ),
        vector=(-0.809017, -0.587785, 0.0),
    ),
    _CourseTopic(
        terms=(
            "embedding",
            "batch size",
            "metadata",
            "provider",
            "revision",
            "dimensions",
            "维度",
            "缓存键",
            "部分返回",
        ),
        vector=(-0.309017, -0.951057, 0.0),
    ),
    _CourseTopic(
        terms=(
            "pgvector",
            "postgresql",
            "cosine distance",
            "hnsw",
            "vector_cosine_ops",
            "文档切片",
            "一个事务",
            "回滚旧内容",
            "向量检索",
            "距离算法",
            "向量写入",
            "旧文档",
        ),
        vector=(0.309017, -0.951057, 0.0),
    ),
    _CourseTopic(
        terms=(
            "contextassembler",
            "context",
            "system",
            "memory",
            "recent",
            "summary",
            "skill",
            "trust",
            "预算",
            "片段",
            "provider token",
        ),
        vector=(0.809017, -0.587785, 0.0),
    ),
)


class CourseRagEvaluationEmbeddingProvider(EmbeddingProvider):
    """Fixed course-topic vectors for the explicit offline pgvector evaluation.

    This intentionally recognises only the bounded course vocabulary. It proves
    pgvector storage and cosine retrieval against the versioned fixture; it is
    not a general-purpose embedding model or a production retrieval claim.
    """

    _metadata = EmbeddingMetadata(
        provider="offline",
        model="course-topic-lexicon",
        revision="v1",
        dimensions=PGVECTOR_DIMENSIONS,
    )

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._metadata

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[tuple[float, float, float], ...]:
        return tuple(self._embed_one(text) for text in texts)

    @staticmethod
    def _embed_one(text: str) -> tuple[float, float, float]:
        normalized = " ".join(_TERM_PATTERN.findall(text.lower()))
        values = [0.0, 0.0, 0.0]
        for topic in _COURSE_TOPICS:
            score = sum(
                len(term) * normalized.count(term)
                for term in topic.terms
            )
            for index, value in enumerate(topic.vector):
                values[index] += score * value
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return (0.0, 0.0, 1.0)
        return (
            values[0] / norm,
            values[1] / norm,
            values[2] / norm,
        )


def create_course_rag_evaluation_embedding_model() -> BatchingEmbeddingModel:
    return BatchingEmbeddingModel(
        CourseRagEvaluationEmbeddingProvider(),
        batch_size=32,
    )


def run_default_pgvector_rag_eval(dsn: str) -> RagRetrievalEvalReport:
    if not dsn.strip():
        raise ValueError("pgvector evaluation dsn must not be empty")
    dataset = load_rag_retrieval_dataset()
    knowledge = PgVectorKnowledgeBase(
        create_psycopg_connection_factory(dsn),
        create_course_rag_evaluation_embedding_model(),
        dimensions=PGVECTOR_DIMENSIONS,
        chunk_size=240,
        overlap=30,
    )
    knowledge.initialize_schema()
    for document in dataset.documents:
        knowledge.add(document.to_document())
    return RagRetrievalEvaluator(
        knowledge,
        dataset,
        retriever_id="pgvector",
    ).evaluate()


def main() -> None:
    report = run_default_pgvector_rag_eval(
        os.environ.get(_EVALUATION_DSN_ENVIRONMENT, "")
    )
    print(json.dumps(report.to_record(), ensure_ascii=False, indent=2))
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

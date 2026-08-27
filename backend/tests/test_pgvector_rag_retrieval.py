from __future__ import annotations

import unittest

from backend.app.evals.pgvector_rag_retrieval import (
    create_course_rag_evaluation_embedding_model,
    run_default_pgvector_rag_eval,
)


class CourseRagEvaluationEmbeddingTest(unittest.TestCase):
    def test_course_topic_embedding_preserves_matching_topic_similarity(self) -> None:
        model = create_course_rag_evaluation_embedding_model()

        query, mcp_document, tool_document = model.embed_batch(
            (
                "MCP Client 为什么要先 initialize？",
                "MCP 客户端先 initialize，再发现工具并管理 STDIO 生命周期。",
                "工具身份和角色来自服务端可信上下文。",
            )
        )

        self.assertEqual(3, model.metadata.dimensions)
        self.assertGreater(
            _dot_product(query, mcp_document),
            _dot_product(query, tool_document),
        )

    def test_pgvector_runner_rejects_empty_dsn(self) -> None:
        with self.assertRaisesRegex(ValueError, "dsn"):
            run_default_pgvector_rag_eval("")


def _dot_product(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(left_value * right_value for left_value, right_value in zip(left, right))

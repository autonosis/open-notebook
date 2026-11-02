import unittest
from unittest.mock import AsyncMock, patch

from open_notebook.utils.chat_retrieval import (
    MAX_CONTEXT_CHARS,
    retrieve_notebook_context,
)


class ChatRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_context_preserves_full_text(self):
        context = {"sources": [{"id": "source:a", "full_text": "the complete paper"}]}
        self.assertIs(await retrieve_notebook_context(context, "authors?"), context)

    async def test_book_is_bounded_scoped_and_retains_original_evidence(self):
        context = {
            "sources": [
                {
                    "id": "source:book",
                    "title": "Book",
                    "full_text": "background " * 340000
                    + "\nThe catalog documents 31 models.",
                    "insights": [],
                }
            ]
        }
        with (
            patch(
                "open_notebook.utils.chat_retrieval.generate_embedding",
                AsyncMock(return_value=[1.0]),
            ),
            patch(
                "open_notebook.utils.chat_retrieval.repo_query",
                AsyncMock(
                    return_value=[
                        {"order": 3676, "content": "The catalog documents 31 models."}
                    ]
                ),
            ) as query,
        ):
            result = await retrieve_notebook_context(context, "how many models?")
        self.assertLess(len(str(result)), MAX_CONTEXT_CHARS)
        self.assertIn("31 models", result["sources"][0]["full_text"])
        self.assertEqual(str(query.await_args.args[1]["source"]), "source:book")
        self.assertIn("WHERE source = $source", query.await_args.args[0])
        self.assertEqual(result["sources"][0]["id"], "source:book")

    async def test_excluded_source_is_not_retrieved_and_insights_only_stays_so(self):
        context = {
            "sources": [{"id": "source:summary", "insights": [{"content": "notes"}]}],
            "notes": [{"id": "note:a", "content": "x" * 130000}],
        }
        with patch(
            "open_notebook.utils.chat_retrieval.repo_query", AsyncMock()
        ) as query:
            result = await retrieve_notebook_context(context, "question")
        query.assert_not_awaited()
        self.assertNotIn("full_text", result["sources"][0])
        self.assertLess(len(str(result)), MAX_CONTEXT_CHARS)

    async def test_retrieval_failure_uses_original_lexical_evidence(self):
        context = {
            "sources": [
                {
                    "id": "source:book",
                    "full_text": "irrelevant " * 20000 + "\nneedle evidence",
                }
            ]
        }
        with patch(
            "open_notebook.utils.chat_retrieval.generate_embedding",
            AsyncMock(side_effect=RuntimeError("offline")),
        ):
            result = await retrieve_notebook_context(context, "needle")
        self.assertIn("needle evidence", result["sources"][0]["full_text"])
        self.assertLess(len(str(result)), MAX_CONTEXT_CHARS)

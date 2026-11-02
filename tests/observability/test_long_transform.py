import tempfile
import unittest
from unittest.mock import patch

from open_notebook.graphs import long_transform as module


class LargeTransformationTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_text_is_dropped_by_split(self):
        text = "section\n" * 70
        parts = module.split_parts(text, 60)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(p) <= 60 for p in parts))

    async def test_failure_resumes_without_repeating_successful_model_calls(self):
        calls = []
        fail = True

        async def generate(text, stage):
            calls.append((text, stage))
            if fail and len(calls) == 2:
                raise RuntimeError("interrupted provider call")
            return "short"

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(module, "DATA_FOLDER", tmp),
        ):
            with self.assertRaises(RuntimeError):
                await module.transform_large(
                    "x" * 160, generate, "model-prompt", limit=60
                )
            fail = False
            calls.clear()
            result = await module.transform_large(
                "x" * 160, generate, "model-prompt", limit=60
            )
            self.assertEqual(result, "short")
            # First map output survives the failed attempt.
            self.assertEqual(
                sum(stage == "partial" and text == "x" * 60 for text, stage in calls), 1
            )
            self.assertTrue(all(len(text) <= 60 for text, _ in calls))
            calls.clear()
            self.assertEqual(
                await module.transform_large(
                    "x" * 160, generate, "model-prompt", limit=60
                ),
                "short",
            )
            self.assertEqual(calls, [])

    async def test_non_contracting_output_stops_instead_of_looping(self):
        async def generate(text, stage):
            return text

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(module, "DATA_FOLDER", tmp),
        ):
            with self.assertRaises(module.IncompleteGenerationError):
                await module.transform_large(
                    "x" * 160, generate, "non-contracting", limit=60
                )


class ResumeSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_source_resume_never_calls_extraction_or_embedding_graph(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from commands.source_commands import (
            SourceProcessingInput,
            process_source_command,
        )

        source = SimpleNamespace(
            id="source:resume",
            full_text="saved book",
            save=AsyncMock(),
            get_insights=AsyncMock(return_value=[]),
        )
        transformation = SimpleNamespace(title="Dense Summary", model_id="model:test")
        request = SourceProcessingInput(
            source_id=source.id,
            content_state={"reuse_extraction": True},
            notebook_ids=[],
            transformations=["transformation:test"],
            embed=True,
        )
        with (
            patch(
                "commands.source_commands.Source.get", AsyncMock(return_value=source)
            ),
            patch(
                "commands.source_commands.Transformation.get",
                AsyncMock(return_value=transformation),
            ),
            patch(
                "commands.source_commands.source_graph.ainvoke", AsyncMock()
            ) as extraction,
            patch(
                "commands.source_commands.transform_graph.ainvoke", AsyncMock()
            ) as transform,
            patch("open_notebook.observability.event"),
        ):
            result = await process_source_command(request)
        self.assertTrue(result.success)
        extraction.assert_not_awaited()
        transform.assert_awaited_once()


class TransformationGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_graph_bounds_calls_and_synthesizes_all_parts(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from langchain_core.messages import AIMessage

        from open_notebook.graphs.transformation import run_transformation

        chain = SimpleNamespace(
            ainvoke=AsyncMock(return_value=AIMessage(content="grounded"))
        )
        transformation = SimpleNamespace(
            title="Dense Summary", prompt="Summarize faithfully"
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(module, "DATA_FOLDER", tmp),
            patch(
                "open_notebook.graphs.transformation.DefaultPrompts",
                return_value=SimpleNamespace(transformation_instructions=None),
            ),
            patch(
                "open_notebook.ai.models.DefaultModels.get_instance",
                AsyncMock(
                    return_value=SimpleNamespace(
                        default_transformation_model="model:test"
                    )
                ),
            ),
            patch(
                "open_notebook.graphs.transformation.provision_langchain_model",
                AsyncMock(return_value=chain),
            ),
        ):
            result = await run_transformation(
                {"input_text": "x" * 240001, "transformation": transformation},
                {"configurable": {}},
            )
        self.assertEqual(result["output"], "grounded")
        self.assertEqual(chain.ainvoke.await_count, 4)
        for call in chain.ainvoke.await_args_list:
            self.assertLessEqual(len(call.args[0][1].content), module.PART_CHARS)
        self.assertIn(
            "Part 3 of 3", chain.ainvoke.await_args_list[-1].args[0][1].content
        )

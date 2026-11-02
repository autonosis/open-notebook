import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pypdfium2

spec = importlib.util.spec_from_file_location("cloud", "/app/local_docling_cloud.py")
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)


class BoundedPDFTests(unittest.TestCase):
    def test_every_page_is_covered_once_without_unbounded_conversion(self):
        ranges = []

        class Converter:
            def convert(self, source, page_range):
                ranges.append(page_range)
                return SimpleNamespace(
                    status=SimpleNamespace(value="success"),
                    document=SimpleNamespace(
                        export_to_markdown=lambda: "extracted batch"
                    ),
                )

        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "test.pdf"
            pdf = pypdfium2.PdfDocument.new()
            for _ in range(33):
                page = pdf.new_page(100, 100)
                page.close()
            pdf.save(str(file))
            pdf.close()
            with (
                patch.dict(os.environ, {"DOCLING_PAGE_BATCH_SIZE": "16"}),
                patch("open_notebook.config.DATA_FOLDER", tmp),
            ):
                output = cloud.extract_bounded(Converter(), file, "markdown")
        self.assertEqual(ranges, [(1, 16), (17, 32), (33, 33)])
        self.assertEqual(output.count("extracted batch"), 3)

    def test_partial_conversion_is_not_silently_accepted(self):
        converter = SimpleNamespace(
            convert=lambda _: SimpleNamespace(
                status=SimpleNamespace(value="partial_success")
            )
        )
        with self.assertRaises(ValueError):
            cloud.extract_bounded(converter, "not-a-local-pdf", "markdown")


class CheckpointTests(unittest.TestCase):
    def test_interrupted_run_reuses_completed_batches_and_invalidates_settings(self):
        calls = []
        fail = True

        class Converter:
            def convert(self, source, page_range):
                calls.append(page_range)
                if fail and page_range == (17, 32):
                    raise RuntimeError("interrupted")
                return SimpleNamespace(
                    status=SimpleNamespace(value="success"),
                    document=SimpleNamespace(
                        export_to_markdown=lambda: str(page_range)
                    ),
                )

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("open_notebook.config.DATA_FOLDER", tmp),
        ):
            file = Path(tmp) / "input.pdf"
            pdf = pypdfium2.PdfDocument.new()
            for _ in range(33):
                pdf.new_page(100, 100).close()
            pdf.save(str(file))
            pdf.close()
            with self.assertRaises(RuntimeError):
                cloud.extract_bounded(Converter(), file, "markdown", {"ocr": True})
            fail = False
            calls.clear()
            output = cloud.extract_bounded(Converter(), file, "markdown", {"ocr": True})
            self.assertEqual(calls, [(17, 32), (33, 33)])
            self.assertIn("(1, 16)", output)
            calls.clear()
            self.assertEqual(
                output,
                cloud.extract_bounded(Converter(), file, "markdown", {"ocr": True}),
            )
            self.assertEqual(calls, [])
            cloud.extract_bounded(Converter(), file, "markdown", {"ocr": False})
            self.assertEqual(len(calls), 3)

    def test_corruption_and_input_change_do_not_reuse_invalid_output(self):
        from open_notebook.extraction_checkpoints import BatchCheckpoints, fingerprint

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.write_bytes(b"first")
            key = fingerprint(source, {})
            cache = BatchCheckpoints(tmp, key)
            cache.write(1, 16, "text")
            self.assertEqual(cache.read(1, 16), "text")
            (cache.directory / "1-16.json").write_text(
                '{"payload":"tampered","sha256":"wrong"}'
            )
            self.assertIsNone(cache.read(1, 16))
            source.write_bytes(b"changed")
            self.assertNotEqual(key, fingerprint(source, {}))


class ProcessorIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_patched_processor_returns_metadata_after_conversion(self):
        from content_core.config import ContentCoreConfig
        from content_core.processors.document import docling

        with (
            patch.object(docling, "DocumentConverter"),
            patch(
                "local_docling_cloud.configure_cloud_enrichment",
                new=__import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(),
            ),
            patch("local_docling_cloud.extract_bounded", return_value="extracted text"),
        ):
            result = await docling.extract_docling("test.pdf", ContentCoreConfig())
        self.assertEqual(result.metadata["docling_format"], "markdown")
        self.assertIn("extracted text", result.content)

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
            with patch.dict(os.environ, {"DOCLING_PAGE_BATCH_SIZE": "16"}):
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

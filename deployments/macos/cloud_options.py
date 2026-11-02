"""Use Docling's supported API VLM engines with the encrypted DeepSeek credential."""

import os


async def configure_cloud_enrichment(options):
    if os.environ.get("DOCLING_CLOUD_PROVIDER") != "deepseek":
        return
    from docling.datamodel.stage_model_specs import VlmModelSpec
    from docling.datamodel.vlm_engine_options import ApiVlmEngineOptions, VlmEngineType

    from open_notebook.ai.models import Model

    model = await Model.get(os.environ["DOCLING_CLOUD_MODEL_ID"])
    if not model or model.provider != "deepseek" or model.name != "deepseek-flash":
        raise ValueError(
            "Docling vision requires the configured image-capable DeepSeek Flash model"
        )
    credential = await model.get_credential_obj()
    if not credential or not credential.api_key:
        raise ValueError("Docling DeepSeek credential is missing")
    endpoint = str(credential.base_url).rstrip("/") + "/docling/chat/completions"
    engine = ApiVlmEngineOptions(
        engine_type=VlmEngineType.API_OPENAI,
        url=endpoint,
        headers={"Authorization": "Bearer " + credential.api_key.get_secret_value()},
        params={"model": model.name},
        timeout=180,
        concurrency=4,
    )

    def spec():
        return VlmModelSpec(
            name="DeepSeek Flash vision",
            default_repo_id=model.name,
            prompt="",
            response_format="plaintext",
            supported_engines={VlmEngineType.API_OPENAI},
            temperature=0,
            max_new_tokens=393216,
        )

    options.enable_remote_services = True
    for stage in [
        options.picture_description_options,
        options.code_formula_options,
        options.chart_extraction_options,
    ]:
        stage.engine_options = engine.model_copy(deep=True)
        stage.model_spec = spec()
    options.picture_description_options.prompt = "Describe the visible figure faithfully. Transcribe readable labels, legend, axes and units. For a diagram list the nodes and directed connections, distinguishing drawn arrows from demonstrated causal evidence. Do not infer missing values or unshown mechanisms. Mark illegible or ambiguous details. Do not assume unlabeled shaded bands are confidence intervals. Do not estimate unlabeled numeric point values. Separate direct observation from interpretation. Begin with: AI-generated figure description (not independently verified)."
    options.picture_description_options.generation_config = {}
    options.chart_extraction_options.use_natural_language_prompts = True
    options.chart_extraction_options.chart2csv = True
    options.chart_extraction_options.chart2summary = False
    options.chart_extraction_options.chart2code = False


def extract_bounded(converter, source, fmt, settings=None):
    """Release rendered PDF pages between batches instead of retaining a book."""
    import gc
    import json
    from pathlib import Path

    import pypdfium2

    from open_notebook.observability import SOURCE, event

    sid = SOURCE.get()
    pages = None
    if (
        isinstance(source, (str, Path))
        and Path(source).is_file()
        and Path(source).suffix.lower() == ".pdf"
    ):
        pdf = pypdfium2.PdfDocument(str(source))
        pages = len(pdf)
        pdf.close()
    batch_size = int(os.environ.get("DOCLING_PAGE_BATCH_SIZE", "16"))
    if batch_size < 1 or batch_size > 64:
        raise ValueError("DOCLING_PAGE_BATCH_SIZE must be between 1 and 64")
    from importlib.metadata import version

    from open_notebook.config import DATA_FOLDER
    from open_notebook.extraction_checkpoints import BatchCheckpoints, fingerprint

    checkpoints = None
    cached_pages = 0
    if pages:
        identity = dict(
            settings or {},
            format=fmt,
            batch_size=batch_size,
            docling=version("docling"),
            schema=1,
            integration=__import__("hashlib")
            .sha256(Path(__file__).read_bytes())
            .hexdigest(),
            cloud_model=os.environ.get("DOCLING_CLOUD_MODEL_ID"),
            cloud_provider=os.environ.get("DOCLING_CLOUD_PROVIDER"),
        )
        checkpoints = BatchCheckpoints(
            Path(DATA_FOLDER) / "extraction_checkpoints", fingerprint(source, identity)
        )
    pieces = []
    for start in range(1, (pages or 1) + 1, batch_size):
        end = min(start + batch_size - 1, pages) if pages else None
        event(
            sid,
            "Extracting text, formulas and images",
            pages_done=start - 1,
            pages_total=pages,
            page_batch_start=start,
            page_batch_end=end,
        )
        cached = checkpoints.read(start, end) if checkpoints else None
        if cached is not None:
            pieces.append(cached)
            cached_pages += end - start + 1
            event(
                sid,
                "Extracting text, formulas and images",
                pages_done=end,
                pages_total=pages,
                cached_pages=cached_pages,
                page_batch_start=start,
                page_batch_end=end,
            )
            continue
        result = (
            converter.convert(source, page_range=(start, end))
            if pages
            else converter.convert(source)
        )
        # Partial/failed conversions must never silently become completed sources.
        if str(result.status.value) not in ("success",):
            raise ValueError(
                f"Docling conversion did not succeed for pages {start}-{end}: {result.status.value}"
            )
        doc = result.document
        if fmt == "html":
            pieces.append(doc.export_to_html())
        elif fmt == "json":
            pieces.append(doc.export_to_dict())
        else:
            pieces.append(
                f"\n\n<!-- PDF pages {start}-{end} -->\n\n" + doc.export_to_markdown()
            )
        if checkpoints:
            checkpoints.write(start, end, pieces[-1])
        del doc, result
        gc.collect()
        event(
            sid,
            "Extracting text, formulas and images",
            pages_done=end,
            pages_total=pages,
        )
    return (
        json.dumps({"page_batches": pieces}) if fmt == "json" else "\n\n".join(pieces)
    )

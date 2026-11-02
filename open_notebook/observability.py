"""Persistent, content-free ingestion telemetry for the pinned local deployment."""

import contextvars
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

from fastapi import APIRouter
from loguru import logger

from open_notebook.config import DATA_FOLDER
from open_notebook.database.repository import ensure_record_id, repo_query

ROOT = Path(
    os.environ.get(
        "OPEN_NOTEBOOK_OBSERVABILITY_DIR", str(Path(DATA_FOLDER) / "observability")
    )
)
ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
# Each process role owns its own rotating sink; no cross-process rotation race.
ROLE = "worker" if any("worker" in arg for arg in sys.argv) else "api"
logger.add(
    str(ROOT / f"{ROLE}.jsonl"),
    filter=lambda r: r["extra"].get("ingestion", False),
    serialize=True,
    rotation="10 MB",
    retention=7,
    compression="gz",
    level="INFO",
    enqueue=True,
)
SOURCE = contextvars.ContextVar("ingestion_source", default=None)


def path(sid):
    if not re.fullmatch(r"source:[A-Za-z0-9_-]+", str(sid)):
        raise ValueError("Invalid source ID")
    return ROOT / (str(sid).split(":")[1] + ".json")


def read(sid):
    try:
        return json.loads(path(sid).read_text())
    except FileNotFoundError:
        return {}


def event(sid, stage, **fields):
    if not sid:
        return
    data = read(sid)
    now = time.time()
    data.update(source_id=str(sid), stage=stage, updated_at=now, **fields)
    data.setdefault("started_at", now)
    tmp = path(sid).with_suffix("." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(data))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path(sid))
    logger.bind(ingestion=True, source_id=str(sid), stage=stage, **fields).info(
        "ingestion_event"
    )


async def _batch_event(command_id, done, total):
    if not command_id:
        return
    rows = await repo_query(
        "SELECT name,args.source_id AS source_id FROM $id",
        {"id": ensure_record_id(command_id)},
    )
    if rows and rows[0].get("name") == "embed_source":
        event(rows[0]["source_id"], "Indexing", chunks_done=done, chunks_total=total)


async def batch_event(command_id, done, total):
    try:
        await _batch_event(command_id, done, total)
    except Exception as exc:
        logger.warning("Embedding telemetry unavailable: {}", type(exc).__name__)


async def snapshot(source):
    sid = str(source.id)
    rows = await repo_query(
        "SELECT id,name,status,args.transformation_id AS transformation_id,args.insight_type AS insight_type,result.success AS success,result.error_message AS result_error,error_message,result.execution_metadata AS metadata,result.execution_time AS duration,args.embed AS requested_embed,args.transformations AS requested_transformations FROM command WHERE args.source_id = $sid",
        {"sid": sid},
    )
    rootid = str(source.command) if source.command else None
    main = next((r for r in rows if str(r["id"]) == rootid), None)
    data = read(sid)
    # Old root process commands can retain stale running flags. Only the source's
    # current root plus explicitly linked child jobs define this ingestion run.
    linked = data.get("jobs", []) if data.get("root_command") == rootid else []
    if linked:
        children = [r for r in rows if str(r["id"]) in linked]
    else:
        # Recover current jobs started before telemetry was installed. No old
        # process_source job is treated as part of the current run.
        children = [
            r
            for r in rows
            if r["name"] in ("embed_source", "create_insight", "run_transformation")
        ]
    jobs = ([main] if main else []) + children
    # Insight creation schedules insight indexing under insight_id, not source_id.
    insights = await repo_query(
        "SELECT id,insight_type FROM source_insight WHERE source = $sid",
        {"sid": ensure_record_id(sid)},
    )
    if insights:
        ijobs = await repo_query(
            "SELECT id,name,status,result.success AS success,error_message,result.error_message AS result_error FROM command WHERE args.insight_id IN $ids",
            {"ids": [str(r["id"]) for r in insights]},
        )
        jobs += ijobs
    active = [
        r
        for r in jobs
        if r["status"] in ("running", "new", "queued", "retrying", "pending")
    ]
    all_failed = [
        r for r in jobs if r["status"] == "failed" or r.get("success") is False
    ]
    failed = [r for r in all_failed if str(r["id"]) == rootid or str(r["id"]) in linked]
    # Before instrumentation, child jobs had no parent/run ID. Keep historical
    # failures visible without claiming an old failed attempt broke today's index.
    historical_failures = [r for r in all_failed if r not in failed]
    if not linked and any(r["name"] == "embed_source" for r in historical_failures):
        if not await source.get_embedded_chunks():
            failed += [r for r in historical_failures if r["name"] == "embed_source"]
    chunks = await source.get_embedded_chunks()
    text_chars = len(source.full_text or "")
    stage = data.get("stage", "Queued")
    if failed:
        state = "failed"
        stage = "Needs attention"
    elif active:
        state = "running"
        if main and main["status"] in ("new", "queued"):
            stage = "Queued for extraction"
        elif main and main["status"] == "running":
            if not text_chars:
                stage = data.get("stage", "Extracting text, formulas and images")
            else:
                stage = data.get("stage", "Generating transformations")
        elif any(r["name"] == "embed_source" for r in active):
            stage = (
                "Indexing"
                if any(
                    r["name"] == "embed_source" and r["status"] == "running"
                    for r in active
                )
                else "Queued for indexing"
            )
        elif any(r["name"] == "create_insight" for r in active):
            stage = "Saving transformations"
        else:
            stage = "Indexing transformations"
    elif main and main["status"] == "completed":
        if main.get("requested_embed") and not chunks:
            state = "unknown"
            stage = "Index missing — needs inspection"
        elif len(insights) < len(main.get("requested_transformations") or []):
            state = "unknown"
            stage = "Requested transformations missing — needs inspection"
        else:
            state = "completed"
            stage = "Ready"
    elif not main and text_chars:
        state = "completed"
        stage = "Ready (legacy source)"
    else:
        state = "unknown"
        stage = "Status unavailable"
    since = data.get("started_at")
    if not since and main:
        try:
            from datetime import datetime, timezone

            stamp = (main.get("metadata") or {}).get("started_at")
            since = (
                datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).timestamp()
                if stamp
                else None
            )
        except (TypeError, ValueError):
            pass
    return dict(
        source_id=sid,
        warnings=[
            "Historical failed attempts are listed below; they are not attributed to the current ingestion run."
        ]
        if historical_failures
        else [],
        title=source.title
        if source.title != "Processing..."
        else Path(source.asset.file_path).name
        if source.asset and source.asset.file_path
        else source.title,
        status=state,
        stage=stage,
        started_at=since,
        updated_at=data.get("updated_at"),
        elapsed_s=round(time.time() - since, 1) if since and active else None,
        text_chars=text_chars,
        embedded_chunks=chunks,
        insights_count=len(insights),
        pages_done=data.get("pages_done"),
        pages_total=data.get("pages_total"),
        page_batch_start=data.get("page_batch_start"),
        page_batch_end=data.get("page_batch_end"),
        chunks_done=data.get("chunks_done"),
        chunks_total=data.get("chunks_total"),
        transformation=data.get("transformation"),
        error=(
            "Worker stopped before completion. Retry required."
            if any(
                str(r.get("error_message", "")).startswith("Worker stopped")
                for r in failed
            )
            else "A processing job failed; inspect correlated local logs."
        )
        if failed
        else None,
        jobs=[
            dict(
                id=str(r["id"]),
                name=r["name"],
                status="failed" if r.get("success") is False else r["status"],
                duration_s=r.get("duration"),
            )
            for r in jobs
        ],
    )


router = APIRouter()


@router.get("/observability/sources")
async def sources_progress():
    from open_notebook.domain.notebook import Source

    rows = await repo_query(
        "SELECT id,created FROM source ORDER BY created DESC LIMIT 100"
    )
    return {
        "sampled_at": time.time(),
        "sources": [await snapshot(await Source.get(str(r["id"]))) for r in rows],
    }


@router.get("/observability/metrics")
async def metrics():
    from fastapi.responses import PlainTextResponse

    rows = await repo_query(
        "SELECT status,count() AS total FROM command GROUP BY status"
    )
    body = "# HELP open_notebook_jobs Persisted job counts by status, including historical jobs.\n# TYPE open_notebook_jobs gauge\n"
    for r in rows:
        status = re.sub("[^a-zA-Z0-9_-]", "", str(r["status"]))
        body += f'open_notebook_jobs{{status="{status}"}} {r["total"]}\n'
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")


def setup(app):
    app.include_router(router, prefix="/api", tags=["local-observability"])

    @app.middleware("http")
    async def request_timing(request, call_next):
        rid = uuid.uuid4().hex
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            logger.bind(
                ingestion=True,
                event="http_request",
                request_id=rid,
                method=request.method,
                path=request.url.path,
                status=500,
                duration_ms=round((time.monotonic() - start) * 1000, 1),
            ).error("http_request_failed")
            raise
        response.headers["X-Request-ID"] = rid
        # No headers, query strings, request bodies, prompts or document text.
        if request.url.path.startswith("/api/") and request.method not in ("OPTIONS",):
            logger.bind(
                ingestion=True,
                event="http_request",
                request_id=rid,
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((time.monotonic() - start) * 1000, 1),
            ).info("http_request")
        return response


async def recover_interrupted_jobs():
    """Only enabled for this deployment's single worker, before it starts jobs."""
    if os.environ.get("OPEN_NOTEBOOK_SINGLE_WORKER_RECOVERY") != "true":
        return
    rows = await repo_query(
        'SELECT id,args.source_id AS source_id FROM command WHERE app = "open_notebook" AND status = "running"'
    )
    for row in rows:
        await repo_query(
            'UPDATE $id SET status = "failed", error_message = $error',
            {
                "id": ensure_record_id(str(row["id"])),
                "error": "Worker stopped before completion. Retry this job; inspect worker restart and memory logs.",
            },
        )
        logger.bind(
            ingestion=True,
            event="interrupted_job",
            command_id=str(row["id"]),
            source_id=row.get("source_id"),
        ).warning("interrupted_job")

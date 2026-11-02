# Persistent ingestion observability

This Autonosis maintenance branch is based on Open Notebook v1.15.0
(315d525). `origin` is autonosis/open-notebook; `upstream` remains
lfnovo/open-notebook. Changes are source-controlled, baked into the derived
image, and do not depend on editing a running container.

## What is visible

Sources > Processing activity refreshes every three seconds while visible.
It shows filenames, extraction/transform/index stages, elapsed time, actual
completed PDF pages and the current page batch, embedding generation counts,
saved chunk/insight counts and correlated job IDs. Details stay expandable
after completion. Failed refreshes are explicitly marked stale.

The source status includes the root job and downstream embedding/insight-save
jobs. A completed extraction alone is not Ready. Requested-but-missing indexes
are reported as unknown/needs inspection. Older commands have no parent/run
metadata; historical failures remain visible and are labelled rather than
misattributed to the current successful ingestion.

## Logs, metrics and privacy

Persistent files under `data/observability`:

- `api.jsonl`: structured HTTP status/latency/request IDs.
- `worker.jsonl`: source stages, counts and interrupted-job events.
- `<source-id>.json`: atomic progress snapshots, surviving recreation.

Structured logs rotate at 10 MB, retaining seven archives per process role,
compressed with gzip. Docker logs additionally use 10 MB x five files per
service in the Compose template. Structured logs exclude request/response
bodies, authentication headers, query strings, documents and generated text.
The pinned worker dependency's unconditional job-argument dumps are redacted
by an asserted build hook; normal dependency errors still appear in local
Docker logs and should be treated as private. Existing pre-patch logs are not
rewritten or uploaded.

Authenticated endpoints (same password protection as the application):

- `GET /api/observability/sources`: ingestion details for the newest 100 sources.
- `GET /api/observability/metrics`: Prometheus text counts of persisted jobs,
  including historical jobs. These counts are not a live-worker count.
- `GET /health`: application health, also used by Docker healthcheck.

No external log/telemetry service is introduced. Existing native DeepSeek
bridge timings remain in the deployment's `logs/deepseek-metrics.jsonl`.

## Large PDFs and worker recovery

`DOCLING_PAGE_BATCH_SIZE=16` bounds retained rendered PDF pages. Text/OCR,
formula recognition and image descriptions remain enabled. Results are
concatenated with explicit original page-range markers. Cross-batch layout or
table continuity may be weaker; HTML consists of concatenated batch exports,
and JSON is a `page_batches` array rather than one Docling document. Partial
Docling conversion is treated as failure. This is bounded-memory processing,
not a guarantee that an arbitrary batch fits every machine.

`OPEN_NOTEBOOK_SINGLE_WORKER_RECOVERY=true` is **only for a deployment with
one worker process**. On worker startup, jobs left running by its predecessor
are marked failed with an explicit interrupted-worker reason; they are not
silently declared active forever or automatically retried without limit.
Do not enable this setting with multiple worker processes or replicas.
Retrying a global-library source is supported, preserves requested
transformations, and refuses an already-active ingestion.

## Build, deploy and rollback

Use `deployments/macos/Dockerfile` with repository-root build context. It builds
the modified frontend and backend, installs pinned Docling dependencies and
asserts the small dependency hooks against the pinned upstream image. In the
existing Mac deployment, Compose selects this checkout as its build context:

```sh
cd /Users/super/Applications/OpenNotebook
docker compose build open_notebook
docker compose up -d --no-deps open_notebook
```

Do not replace a worker during a live ingestion unless interruption is
intentional. The persistent application/database mounts are unchanged.
To roll back, build an earlier reviewed commit in a separate checkout, point
Compose's build context to it, rebuild, then recreate only open_notebook.
No database migration is introduced by this patch. Keep progress/log files
for diagnosis. The original upstream checkout is also retained separately.

Credentials, uploads, model weights, private logs and generated research
content belong outside this repository. Never commit a populated `.env`.

The tracked Compose template is `deployments/macos/compose.yaml`. Set
`OPEN_NOTEBOOK_STATE_DIR` and use a locally populated environment file derived
from `environment.example`. The existing deployment keeps its own root
`compose.yaml`; it builds this fork checkout. Template native adapters are
under `deployments/macos/native`; install them into the deployment's `scripts/`
directory so their relative state paths resolve correctly. Their native
Python dependencies and LaunchAgents must already be provisioned as described
in the deployment operations record. This template is not a one-command
fresh-Mac installer.

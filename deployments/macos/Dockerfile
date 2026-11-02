FROM node:22-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM lfnovo/open_notebook:1.15.0@sha256:54b2025a4a4853c188f74b9b8246eca8c5480e5dd1babfa92db1038ff2f30212
COPY deployments/macos/requirements.lock /tmp/docling-requirements.lock
RUN uv pip install --python /app/.venv/bin/python --torch-backend cpu --no-deps -r /tmp/docling-requirements.lock
COPY deployments/macos/fix_kv_cache.py /tmp/fix_kv_cache.py
RUN /app/.venv/bin/python /tmp/fix_kv_cache.py
COPY deployments/macos/cloud_options.py /app/local_docling_cloud.py
COPY deployments/macos/enable_cloud_options.py /tmp/enable_cloud_options.py
RUN /app/.venv/bin/python /tmp/enable_cloud_options.py
COPY api/ /app/api/
COPY commands/ /app/commands/
COPY prompts/podcast/ /app/prompts/podcast/
COPY open_notebook/ /app/open_notebook/
COPY deployments/macos/redact_worker.py /tmp/redact_worker.py
RUN /app/.venv/bin/python /tmp/redact_worker.py
COPY --from=frontend-builder /build/.next/standalone /app/frontend/
COPY --from=frontend-builder /build/.next/static /app/frontend/.next/static
COPY --from=frontend-builder /build/public /app/frontend/public
COPY frontend/start-server.js /app/frontend/start-server.js

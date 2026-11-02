# Chat-first notebook workspace

The notebook opens in Chat. Sources and Notes are secondary tabs in the same frame; all three panels stay mounted so switching views preserves the draft and active conversation. Existing saved conversations and citation dialogs use the existing API. Source titles wrap; the composer spans the conversation width. The reading area scrolls independently and follows replies only while near the latest message. Navigation moves into a drawer below 1024px.

Chat shows which context is included and links directly to Sources to change it. New sources default to full original content, avoiding a silent substitution of generated insights for paper text. Explicit per-source and per-note choices are stored per notebook in this browser's local storage. Those preferences are device-local; documents, indexes and saved conversations remain in the persistent server database. Drafts survive tab switches, not browser reloads. Very large source sets still require selecting context that fits the chosen model.

## Frontend deployment without restarting ingestion

The Compose `frontend` service runs the built standalone Next server, using the same built image as the backend. The gateway routes UI traffic to this service; API and processing remain in `open_notebook`. Both share the existing persistent database through the API, not a second database. Only the gateway publishes localhost ports. The frontend has a 512 MiB memory limit and restart policy. The existing combined application's unused UI process remains until a later backend packaging change.

From the deployment directory, after applying its private environment and state paths:

```sh
docker compose build open_notebook
docker compose up -d --no-deps frontend
docker compose exec -T gateway nginx -t
docker compose exec -T gateway nginx -s reload
```

Do not recreate `open_notebook` for a frontend-only update during active ingestion. A full `docker compose up -d` can recreate it when the image changes. For rollback, retain the previous image ID under a separate tag before rebuilding, set `frontend.image` to that retained tag, and recreate only `frontend`. Backend/schema updates still require an idle worker and the deployment's normal backup and migration procedures.

## Verification

Production Next/TypeScript build and seven focused component tests passed. The workspace tests exercise default Chat, keyboard tab navigation, and preserving the same draft component across view changes. Existing send shortcuts and header editing tests also passed. Browser checks exercised a real saved notebook: Chat landing, Sources and Notes, draft retention, saved-session list, citation opening the matching original source, and context-choice persistence through reload. Responsive checks use 390px and 768px widths and the normal desktop viewport. No research content or private screenshots belongs in this repository.

No new provider inference was invoked for this layout change. Rendering existing answers and opening their citations verifies UI integration; it does not rerun scientific-answer acceptance tests.

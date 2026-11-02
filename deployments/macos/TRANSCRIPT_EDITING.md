# Editing podcast transcripts

Open Podcasts → an episode’s Details → Transcript → Edit transcript. Search for a word or phrase, then edit individual speaker turns. Save draft stores edits without changing the current audio. Generate revised audio saves pending edits and creates a separate episode using the captured speaker voices. The original stays playable.

Reuse unchanged audio clips is enabled by default. Unchanged turns at the same position reuse the original clip when the voice configuration matches. Changed turns are synthesized locally. Disable reuse to synthesize every turn. The revised episode has its own player and pipeline progress; Go to revised episode focuses its card.

Drafts survive application restarts in the existing SurrealDB episode transcript field. Audio and clips persist in the existing podcast data mount. Existing database/data backups cover both. No schema migration is needed. Closing with unsaved edits asks whether to discard them; browser navigation also warns.

## Implementation and recovery

PUT `/api/podcasts/episodes/{id}/transcript` accepts `expected_revision` and speaker/dialogue `entries`. Saving uses a database compare-and-set; stale saves return 409 rather than overwrite another edit. Saved drafts do not replace the transcript associated with existing audio.

POST `/api/podcasts/episodes/{id}/regenerate-audio` accepts `expected_revision` and `reuse_unchanged`. It snapshots the saved draft and speaker configuration into a new episode, then queues `regenerate_podcast_audio`. No outline or transcript language-model calls occur. Matching repeat requests return the existing revision/job. API submission serialization assumes the current single API process; scale-out requires a distributed submission lock.

The worker reports clip counts, reused clips, assembly and completion. It publishes an audio path only after all segments and assembly succeed. A failed render preserves the original and draft. Retry on a revised episode reruns audio only, using a new output directory. A missing/deleted parent falls back to synthesis using the child’s snapshot. Original clips are reused only when available and valid. Missing credentials or invalid voices fail visibly instead of substituting silence.

This editor changes wording within existing speaker turns. Speaker reassignment, inserting/deleting/reordering turns and automatic factual verification are outside this initial workflow. Editing does not establish source fidelity: check equations, variable meanings and claims against original sources.

The shared generation prompt also asks for spoken explanations of equations and acronym definitions. It is copied into the deployment image; it affects new scripts, not existing audio. There is no automatic transcript rewrite loop.

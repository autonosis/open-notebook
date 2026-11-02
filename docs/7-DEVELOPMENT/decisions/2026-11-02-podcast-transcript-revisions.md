# Persist transcript drafts and render audio as separate revisions

Status: accepted for the Autonosis deployment.

Users need to correct mostly usable scripts without regenerating an outline or losing the existing audio. Keep the audio-associated transcript immutable and store a versioned draft inside the existing flexible transcript envelope. Use compare-and-set saves to reject stale editors. Snapshot a saved draft and captured voices into a separate episode for audio-only rendering.

Render changed turns and optionally reuse identical indexed turns with matching voice configuration. Publish the revised player only after complete assembly; failures retain both original audio and editable draft. No automatic language-model review loop is introduced. This preserves user control over wording and avoids additional script-generation calls.

This needs no database migration. Existing data/database backups cover drafts and revised audio. The single-process API uses an in-process submission lock plus database revision checks; distributed API deployment requires a distributed submission claim. Initial editing supports text within existing speaker turns, not structural transcript editing.

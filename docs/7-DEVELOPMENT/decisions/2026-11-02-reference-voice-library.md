# Keep cloned reference voices in the local speech service

Status: accepted for the Autonosis deployment.

Expose model capability discovery and a reference-voice library through the existing authenticated application API. The native service normalizes and persists uploads and advertises saved IDs in its ordinary voice catalog. Speaker profiles store these stable IDs, allowing both original podcast generation and audio-only revisions to use the normal TTS protocol.

References stay in the native application's persistent data tree and never enter Git or language-model prompts. Capability discovery distinguishes the installed Qwen CustomVoice presets from a hypothetical Qwen Base deployment. The bridge only accepts the configured private native speech endpoints; it does not infer cloud upload consent from a model name.

Archive instead of deleting references from the UI: historical profile snapshots and audio revisions may still need them. This creates a retention obligation, documented in the operator guide. No new SurrealDB table or application migration is needed. The first implementation supports Chatterbox English cloning, upload or browser recording, generated auditions, and prefilled speaker profile creation. Real-speaker similarity remains an owner listening acceptance check.

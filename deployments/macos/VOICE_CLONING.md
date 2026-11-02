# Local voice cloning

Podcasts → **Voice cloning** is the reference-voice workspace. Choose a capable model, enter a name, and record or upload a sample. Listen to the reference, save it, and use **Preview voice** to audition new speech. **Create speaker profile** opens the normal profile form with that model and voice preselected; add other speakers there. Saved clones also appear by name in the normal Chatterbox voice selector.

Recording asks the browser for microphone access only when Record my voice is pressed. Stop manually or let the 30-second limit stop it. Leaving the view releases microphone tracks, including a permission request that resolves after leaving. Upload is an alternative when permission is denied or recording is unsupported. Samples must contain 5–30 seconds of clear English speech from one speaker, without music, and be at most 10 MB. About 10–15 seconds is a useful starting point. Reference quality affects similarity; a saved voice is not proof of naturalness or identity fidelity.

## Supported models

- **Chatterbox:** local reference-audio cloning using the already installed MLX model. This deployment currently synthesizes English.
- **Qwen3-TTS Base:** select `qwen3-tts-base` for local cloning. Enter the exact words spoken in the reference recording. Use suggested recording text fills a script to read aloud. Both audio and matching text are saved privately; they are not sent to a language model. The current integration synthesizes English.
- **Qwen3-TTS CustomVoice:** the existing `qwen3-tts` model retains its nine preset speakers; it remains separate from Base.
- **Kokoro:** preset voices; remains the default. Cloning is not advertised for it.

This is reference-conditioned synthesis, not training a new model. No personal recording is bundled or committed. Use your voice or recordings you have permission to use.

## Persistence and privacy

The native speech service owns `data/voice_clones/clone_<uuid>/voice.json` and `reference.wav` in the application state directory. The sample is decoded into mono 24 kHz PCM WAV; the raw upload is discarded. Directories are mode 700; reference and metadata files are mode 600. Metadata stores the display name, duration, timestamp, archival flag and normalized-audio SHA-256. The native config's `clones_dir` points here. Existing data backups include these files; treat backups as private recordings.

The application bridges authenticated requests to the private native endpoint. Recordings are accepted only for this deployment's local speech endpoints; familiar model names with cloud URLs are rejected. Redirects and environment HTTP proxies are disabled for this bridge. Browser requests use the application's existing password authentication. The native service has its separate private bearer credential and no published network port. Logs use voice IDs/counts, not recording contents.

Podcast script generation still uses the configured language provider (currently DeepSeek); cloning references and speech synthesis stay local. Preview audio is retained in the existing authenticated `data/notebook/voice_previews` cache. Saved profile snapshots retain voice IDs for episode regeneration.

**Archive** hides a voice from new catalog selections. **Show archived → Restore** makes it selectable again. Archived references are retained so existing profiles and episodes can still synthesize speech. Archiving is not erasure. Do not manually remove reference directories that are used by saved profiles or historical episodes.

## Protocol and recovery

Application endpoints under `/api/podcasts/voice-cloning`: GET `models`; GET/POST `voices` (multipart model_id/name/file, plus reference_text for Qwen Base); PATCH `voices/{id}` with archived flag and model_id; GET `voices/{id}/reference` with model_id. Provider routes mirror these under `/v1/chatterbox/audio` or `/v1/qwen3-tts-base/audio`, with `clone-capabilities` for capability discovery. Ordinary `/audio/voices` and `/audio/speech` use the saved clone IDs, so podcast generation and transcript audio revisions require no special path handling.

Uploads are bounded before forwarding and again by the native service. FFmpeg is restricted to expected audio containers and local file/pipe protocols, validates actual decoded duration and rejects silent samples. Voice IDs are server-created UUIDs, never paths. Existing references resolve through directory enumeration rather than path joins from request IDs; symlinks are rejected. Unsaved recording previews decode binary audio with Web Audio rather than interpreting file-derived URLs. Failed imports remove partial references; metadata publication is atomic. No background training status is invented: Save stores the reference, and Preview shows the actual synthesis wait.

Update the fork and pinned native requirements, wait for active speech/podcast jobs, then restart `local.open-notebook.tts` and redeploy the API/frontend using the existing operations guide. The native adapter now requires `python-multipart==0.0.33`. Restarting either component retains the voice library. Back up/restore data, config and credentials together. Restore voice directories before attempting to regenerate episodes that reference them.

Upstream: https://github.com/Blaizzy/mlx-audio/blob/main/docs/guides/voice-cloning.md and https://github.com/Blaizzy/mlx-audio/blob/main/docs/models/tts/chatterbox.md.

## Qwen Base checkpoint

Pinned MLX conversion: mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit, revision e7dd0585652209fa0d7783659aad4e8a324de11c, about 3.1 GB, Apache-2.0. Upstream provenance: Qwen/Qwen3-TTS-12Hz-1.7B-Base. Uses installed mlx-audio 0.6.3 without upgrading the native runtime. The native setup/download scripts provision/register Base idempotently. Saved references are scoped to their backend and cannot be used through another backend by changing the endpoint. One inference thread and one resident speech model are retained across Base, CustomVoice and Chatterbox. Reference text is limited to 4000 characters for the 5–30 second recording; this is not a language-model output token limit.

# Optional native Qwen and Chatterbox speech

Kokoro remains the default. Optional `qwen3-tts`, `qwen3-tts-base` and `chatterbox` models are registered as `openai_compatible` speech providers. No existing notebook, model, speaker profile, episode profile or language-model default is replaced. Piper is not registered.

Podcasts → Profiles has two optional speaker pairs and matching episode profiles:

| Episode profile | Speaker profile | Voices |
|---|---|---|
| Qwen local research | Qwen English pair | Ryan / Aiden |
| Chatterbox local research | Chatterbox English pair | Heart / Michael, synthetic references |

Select the episode profile when generating a podcast, or edit any speaker profile to select its voice model. The voice dropdown lists nine named Qwen presets or two Chatterbox references; inline auditions use the selected model. Qwen's multilingual presets are exposed, but this integration's acceptance tests use English. Chatterbox also supports saved reference voices through Podcasts → Voice cloning. See [VOICE_CLONING.md](VOICE_CLONING.md) for recording/upload, auditions, profile handoff and private storage. Qwen Base is registered separately for cloning with reference audio and exact reference text. The existing Qwen CustomVoice variant remains preset-only.

## Architecture and persistence

Native macOS LaunchAgent `local.open-notebook.tts` runs the tracked `deployments/macos/native/local_tts.py` using the dedicated state-directory `.tts-venv`. It starts at user login and recovers after process failure. `ProcessType=Interactive` is intentional: the daemon-default process stalled during imports on this Mac; Interactive startup passed. This changes only this application's LaunchAgent priority.

The service binds **127.0.0.1:11438**, requires a private bearer token for inference/catalog APIs, and uses the native MLX Metal runtime. The Docker backend retains its internal network. Its existing gateway bridges internal port 11438 to the host; that gateway port is not published. Models use separate base URLs so Esperanto can retrieve the appropriate voice catalog without needing a model query argument:

- `http://gateway:11438/v1/qwen3-tts`
- `http://gateway:11438/v1/qwen3-tts-base`
- `http://gateway:11438/v1/chatterbox`

Routes: `GET /models`, `GET /audio/voices`, `POST /audio/speech` relative to each base URL. Speech accepts standard `model`, `voice`, `input`, `response_format` and optional `speed`. MP3, WAV and 24 kHz mono PCM are supported. Invalid voices/model paths/unsupported formats are rejected. Reference uploads use the separate authenticated clone endpoints described in VOICE_CLONING.md. WAV/MP3 encode before response; this is buffered speech for the podcast library, not a streaming client API. Tempo changes use local FFmpeg.

One dedicated inference thread serializes all Metal access. Only one of Qwen/Chatterbox is resident, and Chatterbox conditions are cached separately per voice. Switching models releases the previous model and Metal cache. Five idle minutes unload the optional model. A two-request queue rejects excess requests with HTTP 429; canceled callers keep their slot until native inference finishes. Long turns are divided at word boundaries into 1,000-character spans, keeping each synthesis well within the 4,096-audio-token runaway guard. This is separate from language-model output settings.

Persistent state under `OPEN_NOTEBOOK_STATE_DIR`:

- `.tts-venv`: isolated pinned dependencies, no Piper package.
- `models/tts-evaluation`: existing dedicated Hugging Face cache reused without duplicating weights. The historical directory name is retained to preserve evaluation paths.
- `models/native-tts/manifest.json`: pinned production model paths/provenance.
- `models/native-tts/references`: synthetic Kokoro references, never real-person recordings.
- `config/local-tts.json` and `config/local-tts.key`: private configuration/token; token mode 600, encrypted copy in the existing app credential store.
- `logs/local-tts.jsonl`: rotating request records, IDs/model/voice/character count/duration/error type, never prompt text or token values. Native stdout/stderr are separate startup diagnostics.
- Existing `data/notebook/voice_previews` and podcast directories retain generated audio.

Models: Qwen MLX 1.7B CustomVoice 8-bit, revision `41d3337e8b7f2843a75841595fc14e4b9a7a4b96` (Apache-2.0); Chatterbox Multilingual V3 MLX revision `03565773edd72e949572557597af8063bb49a18a` (MIT); S3TokenizerV2 revision `e0c9886f0e1c35ae85b1f27277416fb19fc72bec`. These are community MLX conversions. Native runtime: Python 3.11.14, mlx-audio 0.6.3, MLX 0.32.4. Full dependencies are pinned in `native/tts-requirements.lock`.

## Provision / recover

Use the dedicated state directory and existing local Kokoro service. No existing Python environment is modified. FFmpeg must be installed and on PATH during setup.

```sh
export OPEN_NOTEBOOK_STATE_DIR="$HOME/Applications/OpenNotebook"
cd "$HOME/git/open-notebook"
uv venv --python 3.11 "$OPEN_NOTEBOOK_STATE_DIR/.tts-venv"
uv pip sync --python "$OPEN_NOTEBOOK_STATE_DIR/.tts-venv/bin/python" deployments/macos/native/tts-requirements.lock
"$OPEN_NOTEBOOK_STATE_DIR/.tts-venv/bin/python" deployments/macos/native/download_local_tts.py --state-dir "$OPEN_NOTEBOOK_STATE_DIR"
# Include the internal 11438 server block from deployments/macos/nginx.conf
# in the deployment gateway config, then nginx -t and nginx -s reload.
"$OPEN_NOTEBOOK_STATE_DIR/.tts-venv/bin/python" deployments/macos/native/setup_local_tts.py --state-dir "$OPEN_NOTEBOOK_STATE_DIR"
```

Download contacts Hugging Face once and uses local Kokoro only to create missing synthetic reference clips. The S3Tokenizer cache's `main` alias is pinned locally to the recorded revision because the Chatterbox loader requests that alias. The running service has HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE enabled. Inference requires no cloud API; podcast outline/script generation retains the user's DeepSeek configuration and therefore remains a cloud language-model operation.

Setup is idempotent by credential/model/profile identity and asserts defaults stay unchanged. Existing speaker/profile edits are preserved. A rerun starts an existing stopped service without restarting a running one. Source upgrades require the explicit restart command after all active speech/podcast requests finish.

```sh
# Health; no token or prompt printed
curl http://127.0.0.1:11438/health
launchctl print "gui/$(id -u)/local.open-notebook.tts"
# Restart only after active speech/podcast work finishes
launchctl kickstart -k "gui/$(id -u)/local.open-notebook.tts"
# Stop / start across the current login session
launchctl bootout "gui/$(id -u)/local.open-notebook.tts"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/local.open-notebook.tts.plist"
# Auditions; add --podcasts for short synthetic end-to-end acceptance episodes
"$OPEN_NOTEBOOK_STATE_DIR/.tts-venv/bin/python" deployments/macos/native/verify_local_tts.py --state-dir "$OPEN_NOTEBOOK_STATE_DIR"
```

Update source through the Autonosis fork, synchronize the dedicated lock only when deliberately upgrading, run protocol/unit checks plus live auditions, then restart only this LaunchAgent. Roll back the native adapter/config/lock together; Kokoro remains usable if optional models are stopped. Back up the config/token, model manifest/reference clips and LaunchAgent alongside the existing application/database backup. Models can be fetched from pinned revisions; audio and credentials require the normal persistent-state backup.

## Validation

Six focused protocol/lifecycle tests cover authentication, voice routing, invalid input, sanitized failures/recovery, queue cancellation, model eviction, per-voice conditionals and long-turn word preservation. Live app catalog and four auditions passed; local ASR recovered the complete fixed preview sentence for both Qwen and both Chatterbox voices. Additional full-podcast and restart acceptance evidence is recorded in the deployment's VALIDATION.md; do not treat a submitted job as complete.

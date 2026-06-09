# Odysseus ↔ Local AI Cat — Companion Handover

Last updated: 2026-06-09. Purpose: pick this work up cleanly on another machine.

This project wraps the MIT-licensed **odysseus** AI-workspace as a macOS companion app
whose entire AI backend is **Local AI Cat** (a local OpenAI-compatible server on
`http://127.0.0.1:11434/v1`). This doc is the single source of truth for the current
state and the remaining plan. It spans **two repos**.

---

## 1. Repos, branches, remotes

| Repo | Local path (this machine) | Branch | Remote |
|---|---|---|---|
| **Odysseus fork** | `/Users/timapple/Documents/Guest/odysseus` | `cat-companion` | `origin` = `git@github.com:local-ai-cat/odysseus.git` (push via HTTPS + **phil-simcity** gh account), `upstream` = `pewdiepie-archdaemon/odysseus` |
| **Local AI Cat** | `/Users/timapple/Documents/Github/Local-AI-Chat` | `feat/dangerously-skip` | `origin` (atlascodes); all work lands on `outdoor-cat`, `main` is release-only |

**Both branches are now pushed** (as of 2026-06-09). `cat-companion` previously existed
**only locally with no remote backup** — that risk is closed.

> gh account note: `local-ai-cat` org is owned by the **phil-simcity** gh account, not the
> default-active `atlascodesai`. To push odysseus: `gh auth switch -u phil-simcity`,
> `gh auth setup-git`, set the push URL to HTTPS, push, then `gh auth switch -u atlascodesai`.
> (SSH to `local-ai-cat` is **not** authorized for the default key.)

---

## 2. New-machine setup

### Odysseus
```bash
git clone git@github.com:local-ai-cat/odysseus.git   # or HTTPS via phil-simcity
cd odysseus && git checkout cat-companion
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python setup.py                 # creates SQLite + admin user, prints a temp password
# Recreate .env (gitignored). Minimum keys:
#   LLM_HOST=127.0.0.1
#   APP_PORT=7860               # 7000 is held by macOS AirPlay
#   SEARXNG_INSTANCE=...        # optional; DuckDuckGo is the default search provider
uvicorn app:app --host 127.0.0.1 --port 7860
```
On startup, `src/cat_seed.py::seed_cat_endpoint()` auto-registers the cat at
`127.0.0.1:11434/v1`, classifies models (hides speech models from the chat picker),
wires whisper-1 as STT, and self-heals a stale searxng provider → duckduckgo.

Run tests (canonical, repo venv — NOT the frozen-app bundle):
```bash
make test     # 2163 passed, 1 skipped, ~22s
```

### Local AI Cat (the backend)
Build the macOS app and enable its local API:
- Scheme `Seek Deep Local AI`; `xcodebuild ... -destination platform=macOS build CODE_SIGNING_ALLOWED=NO`
- Local API is opt-in via UserDefaults: `localAPI.enabled`, `localAPI.port` (default 11434),
  `localAPI.requiresToken`. Dev build bundle id `pldev.Seek-Deep-Local-AI.dev`.
- Models shared at `~/Library/Caches/models/`.

---

## 3. What the cat already powers (verified)

Chat (stream + non-stream), agent tool-calling (harmony / Qwen-XML / DeepSeek / Hermes
dialects), **vision** (cat supports `image_url` + has a text-only-model bridge — needs a VL
model loaded, e.g. Gemma 3 / Qwen-VL), STT (`/v1/audio/transcriptions`, whisper-1).
RAG works **today** via odysseus-local FastEmbed; web search works **today** via odysseus's
built-in DuckDuckGo (no key). Deep Research works (LLM = cat, web = DDG; default-off).

Cat API surface lives in `LocalAIHTTPRouter.swift` (+ `LocalTranscriptionAPIServer.swift`
binds :11434). Dialects: `ToolCallDialect.swift`, streaming harmony parser
`HarmonyStreamParser.swift`. The gpt-oss harmony fix is committed + verified on both sides.

---

## 4. Remaining plan

### Phase 1 — `/v1/embeddings` on the cat  ← MAIN REMAINING WORK
The cat has **no embedding runtime today** (confirmed: no `MLXEmbedders`, no embedding
model in the catalog). This is net-new and is the agreed scope. Dual-purpose: serves
odysseus RAG **and** the cat's own `UnifiedMemoryManager` semantic recall.

- Add `MLXEmbedders` (from `mlx-swift-examples`) as the embedding runtime.
- Add an embedding model to the catalog + download/load wiring (reuse `/v1/local/models/*`).
  **Chosen model: `bge-small-en-v1.5`** (~130MB, fast, strong for RAG). Alternatives if
  needed: nomic-embed-text (longer context) or bge-m3 (multilingual).
- Implement `POST /v1/embeddings` in `LocalAIHTTPRouter` (+ route in
  `LocalTranscriptionAPIServer`). OpenAI shape: `{input, model}` →
  `{object:"list", data:[{object:"embedding", embedding:[...], index}], model, usage}`.
  Batch-capable (`input` may be a string or array).
- Wire the cat's `UnifiedMemoryManager` to use it.
- Add to the Ollama `/api/tags` + `/v1/models` listings as a non-chat model so odysseus's
  classifier keeps it out of the chat picker (same path as speech models).

### Phase 2 — Odysseus consumes cat embeddings
- `src/cat_seed.py` auto-wires the embedding endpoint to cat's `/v1/embeddings` when the
  embed model is present, with **FastEmbed as the fallback** (graceful if not downloaded).
- Touch points: `routes/embedding_routes.py`, `src/chroma_client.py` (embedded
  PersistentClient), `src/chat_processor.py` (RAG retrieval threshold >0.35).

### Phase 3 — Real e2e harness (layered, CI-runnable)
- **L1 cat (in-process, real HTTP socket):** XCTest spins up the real `LocalAIHTTPServer`
  and hits `/v1/chat/completions`, `/v1/models`, `/v1/audio/transcriptions`, **`/v1/embeddings`**
  over a socket. Closes the "all-mocked, no real HTTP" gap.
  Existing tests: `LocalAIHTTPServerTests.swift`, `HarmonyStreamParserTests.swift`,
  `ToolCallExtractorsTests.swift`, `ModelLifecycleConsistencyTests.swift`.
- **L2 odysseus (pytest vs a contract-fake cat server):** real `seed_cat_endpoint`, model
  classification (chat vs speech), STT endpoint dispatch (`services/stt/stt_service.py::_transcribe_api`),
  embeddings client → ChromaDB storage. These are all **currently untested**.
  New files: `tests/test_cat_seed_integration.py`, `tests/test_stt_endpoint_integration.py`,
  `tests/test_embeddings_endpoint_integration.py`.
- **L3 full-live (self-hosted runner only, gated):** build the cat, run it with a tiny model,
  promote `scripts/verify_cat_connection.py` to assert real generation **and** real embeddings.
  Only layer needing a GPU → stays manual / runner-gated.

### Out of scope (decided 2026-06-09)
- **Image generation** — cat has no `/v1/images`. Default-ON odysseus image tool currently
  fails → **default-disable the image-gen tool in odysseus config** (settings: `image_gen_enabled`).
  Not adding `/v1/images` to the cat for now.
- **TTS** — cat has no `/v1/audio/speech`; odysseus TTS is default-off. Leave as-is.

---

## 5. Test-coverage gaps (what "fully covered" requires)

Today almost everything is mocked/unit-only; there is **no real cat↔odysseus round-trip test**.
Untested paths to close (see Phase 3): `seed_cat_endpoint`, `_classify_cat_models`, STT
`endpoint:id` dispatch, embeddings client + ChromaDB storage, and the cat's `/v1/embeddings`
(does not exist yet). `scripts/verify_cat_connection.py` is a manual script, not CI.

---

## 6. Known gotchas
- Cold-start: cat takes ~40–100s to *load* a model first time, then fast. Pre-warm or rely on
  the STREAM_TIMEOUT 600 bump (`f000d7d`).
- `save_settings` materializes the full dict, so DEFAULT_SETTINGS changes only affect
  never-saved installs → use the cat_seed **self-heal** pattern for already-run installs.
- Frozen dev+prod apps share `~/Library/Application Support/Odysseus` (not isolated per variant).
- Built-in MCP server scripts are inert in the frozen app (collected as PYZ, not on-disk) —
  fix with `--add-data mcp_servers:mcp_servers` if those features are wanted.
- Never reuse dev tags on the cat (TCC permission corruption) — use fresh tags.

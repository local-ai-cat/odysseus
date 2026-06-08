"""Auto-connect the Local AI Cat companion to its model server at startup.

The cat companion ships pointed at a local OpenAI-compatible server (the
"Local AI Cat" macOS app) exposing /v1 at http://127.0.0.1:11434. Out of the
box odysseus registers no endpoints, so a fresh install shows an empty model
picker. This module idempotently registers the cat as a shared model endpoint
on boot so its live models appear with zero manual setup.

Design notes:
  * Best-effort: every failure is swallowed so a seed problem never blocks app
    startup.
  * Idempotent: dedupes on base_url, so reboots don't create duplicate rows and
    a user's manually-added cat endpoint is reused (and refreshed) rather than
    duplicated.
  * Resilient to a not-yet-running cat: the row is registered even when the cat
    is unreachable at boot, with auto-refresh on, so odysseus's background model
    refresh (kicked by the UI's /api/models polling) fills in models the moment
    the cat comes online — no restart needed.
  * owner=None makes the endpoint shared/visible to all users, including the
    auth-disabled desktop ("" / no-login) user.

Env knobs:
  LOCALAI_CAT_SEED            "0"/"false"/"no"/"off" disables seeding (default on)
  LOCALAI_CAT_BASE_URL        cat /v1 base (default http://127.0.0.1:11434/v1)
  LOCALAI_CAT_API_KEY         optional bearer key (localhost cat needs none)
  LOCALAI_CAT_REFRESH_INTERVAL  seconds between background model refreshes (default 60)
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import uuid

logger = logging.getLogger(__name__)

CAT_ENDPOINT_NAME = "Local AI Cat"
DEFAULT_CAT_BASE_URL = "http://127.0.0.1:11434/v1"

# Model ids whose name marks them as non-chat regardless of metadata (defence in
# depth on top of the capability check below).
_NONCHAT_NAME_HINTS = ("whisper", "speech", "tts", "embed", "rerank", "moderation")


def _preferred_default(chat_models: list[str]) -> str | None:
    """Pick a friendly default chat model: skip reasoning (-r1), coder, vision
    (-vl) and very large (120b/70b/...) models when a plain general instruct
    model is available, so the first-run default is fast and conversational."""
    if not chat_models:
        return None
    special = ("-r1", "reasoning", "-vl", "vl-", "coder", "embed")
    huge = ("120b", "405b", "70b", "72b")
    general = [m for m in chat_models if not any(s in m.lower() for s in special)]
    pool = general or chat_models
    smaller = [m for m in pool if not any(h in m.lower() for h in huge)]
    pool = smaller or pool
    return pool[0]


def _classify_cat_models(base: str, api_key: str | None, timeout: float = 4.0):
    """Fetch the cat's /v1/models and split chat LLMs from speech/transcription.

    The cat tags real chat/vision models with `context_length`/`max_output_tokens`
    in its OpenAI model list; speech models (whisper-1, apple-speech,
    speech-analyzer) carry neither. We classify on that so transcription models
    don't show up as selectable chat LLMs. Returns (all_ids, chat_ids,
    nonchat_ids); on any failure returns ([], [], []) so the caller can fall back.
    """
    req = urllib.request.Request(base.rstrip("/") + "/models")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return [], [], []

    all_ids, chat_ids, nonchat_ids = [], [], []
    for m in data.get("data", []):
        mid = m.get("id")
        if not mid:
            continue
        all_ids.append(mid)
        name_is_nonchat = any(h in mid.lower() for h in _NONCHAT_NAME_HINTS)
        has_chat_caps = bool(m.get("context_length") or m.get("max_output_tokens"))
        if has_chat_caps and not name_is_nonchat:
            chat_ids.append(mid)
        else:
            nonchat_ids.append(mid)
    return all_ids, chat_ids, nonchat_ids


def _seed_enabled() -> bool:
    return os.getenv("LOCALAI_CAT_SEED", "1").strip().lower() not in ("0", "false", "no", "off", "")


def _cat_base_url() -> str:
    return os.getenv("LOCALAI_CAT_BASE_URL", DEFAULT_CAT_BASE_URL).strip() or DEFAULT_CAT_BASE_URL


def _refresh_interval() -> int:
    try:
        return max(15, min(86400, int(os.getenv("LOCALAI_CAT_REFRESH_INTERVAL", "60"))))
    except ValueError:
        return 60


def seed_cat_endpoint() -> dict:
    """Idempotently register the local cat as a model endpoint. Never raises.

    Returns a small status dict (also useful for the verification harness).
    """
    result = {
        "seeded": False,
        "endpoint_id": None,
        "base_url": None,
        "models": 0,
        "reachable": False,
        "reason": "",
    }
    if not _seed_enabled():
        result["reason"] = "disabled via LOCALAI_CAT_SEED"
        return result

    try:
        from core.database import ModelEndpoint, SessionLocal
        from src.endpoint_resolver import _first_chat_model, normalize_base
        from src.settings import load_settings, save_settings
    except Exception as e:  # noqa: BLE001
        logger.warning("⚠️ cat seed: import failed (%s) — skipping", e)
        result["reason"] = f"import failed: {e}"
        return result

    base = normalize_base(_cat_base_url())
    result["base_url"] = base
    api_key = os.getenv("LOCALAI_CAT_API_KEY") or None

    # /v1/models lists instantly even when the cat is cold (only generation is
    # slow), so a short timeout is fine. Classify chat LLMs vs speech models so
    # transcription models (whisper-1, apple-speech, speech-analyzer) don't show
    # up as selectable chat models. Tolerate a down cat → register offline.
    models, chat_models, nonchat_models = _classify_cat_models(base, api_key)
    result["reachable"] = bool(models)
    result["models"] = len(models)
    result["chat_models"] = len(chat_models)
    result["nonchat_models"] = nonchat_models

    ep_id = None
    db = SessionLocal()
    try:
        existing = db.query(ModelEndpoint).filter(ModelEndpoint.base_url == base).first()
        if existing is not None:
            ep_id = existing.id
            changed = False
            if models:
                existing.cached_models = json.dumps(models)
                # Hide non-chat (speech) models from the chat picker.
                existing.hidden_models = json.dumps(nonchat_models) if nonchat_models else None
                changed = True
            if not existing.is_enabled:
                existing.is_enabled = True
                changed = True
            if changed:
                db.commit()
            result["reason"] = "already registered"
        else:
            ep_id = str(uuid.uuid4())[:8]
            db.add(ModelEndpoint(
                id=ep_id,
                name=CAT_ENDPOINT_NAME,
                base_url=base,
                api_key=api_key,
                is_enabled=True,
                model_type="llm",
                endpoint_kind="local",
                model_refresh_mode="auto",
                model_refresh_interval=_refresh_interval(),
                cached_models=json.dumps(models) if models else None,
                # Speech/transcription models stay in cached_models (known to the
                # system, available for a future STT hookup) but are hidden from
                # the chat model picker.
                hidden_models=json.dumps(nonchat_models) if nonchat_models else None,
                owner=None,  # shared → visible to all users (incl. auth-disabled "local")
            ))
            db.commit()
            result["seeded"] = True

        # Make the cat the default chat endpoint/model when none is chosen yet,
        # AND self-heal a default that points at a now-hidden speech model (an
        # earlier build could pick apple-speech). Pick from CHAT models only.
        if chat_models:
            try:
                settings = load_settings()
                cur_model = settings.get("default_model") or ""
                no_default = not settings.get("default_endpoint_id")
                bad_default = cur_model in nonchat_models  # e.g. a speech model
                if no_default or bad_default:
                    settings["default_endpoint_id"] = ep_id
                    settings["default_model"] = _preferred_default(chat_models) or _first_chat_model(chat_models) or chat_models[0]
                    save_settings(settings)
                    if bad_default:
                        logger.info("🔧 cat seed: reset default model %r → %r (speech model is not a chat model)",
                                    cur_model, settings["default_model"])
            except Exception as e:  # noqa: BLE001
                logger.warning("⚠️ cat seed: setting default model failed: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.warning("⚠️ cat seed: db write failed: %s", e)
        result["reason"] = f"db write failed: {e}"
    finally:
        db.close()

    result["endpoint_id"] = ep_id
    if result["reachable"]:
        logger.info("✅ cat seed: '%s' connected — %d chat models (%d speech models hidden) at %s",
                    CAT_ENDPOINT_NAME, result["chat_models"], len(nonchat_models), base)
    else:
        logger.info("🔍 cat seed: '%s' registered but cat not reachable at %s yet "
                    "(will auto-connect when it starts)", CAT_ENDPOINT_NAME, base)
    return result

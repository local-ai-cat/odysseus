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
import uuid

logger = logging.getLogger(__name__)

CAT_ENDPOINT_NAME = "Local AI Cat"
DEFAULT_CAT_BASE_URL = "http://127.0.0.1:11434/v1"


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
        from routes.model_routes import _probe_endpoint
        from src.endpoint_resolver import _first_chat_model, normalize_base
        from src.settings import load_settings, save_settings
    except Exception as e:  # noqa: BLE001
        logger.warning("⚠️ cat seed: import failed (%s) — skipping", e)
        result["reason"] = f"import failed: {e}"
        return result

    base = normalize_base(_cat_base_url())
    result["base_url"] = base

    # /v1/models lists instantly even when the cat is cold (only generation is
    # slow), so a short timeout is fine. Tolerate a down cat → register offline.
    try:
        models = _probe_endpoint(base, os.getenv("LOCALAI_CAT_API_KEY") or None, timeout=4) or []
    except Exception as e:  # noqa: BLE001
        logger.info("🔍 cat seed: probe failed (%s) — registering offline", e)
        models = []
    result["reachable"] = bool(models)
    result["models"] = len(models)

    ep_id = None
    db = SessionLocal()
    try:
        existing = db.query(ModelEndpoint).filter(ModelEndpoint.base_url == base).first()
        if existing is not None:
            ep_id = existing.id
            changed = False
            if models:
                existing.cached_models = json.dumps(models)
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
                api_key=os.getenv("LOCALAI_CAT_API_KEY") or None,
                is_enabled=True,
                model_type="llm",
                endpoint_kind="local",
                model_refresh_mode="auto",
                model_refresh_interval=_refresh_interval(),
                cached_models=json.dumps(models) if models else None,
                owner=None,  # shared → visible to all users (incl. auth-disabled "")
            ))
            db.commit()
            result["seeded"] = True

        # Make the cat the default chat endpoint/model if the user hasn't picked
        # one yet (and we actually have a model to point at).
        if models:
            try:
                settings = load_settings()
                if not settings.get("default_endpoint_id"):
                    settings["default_endpoint_id"] = ep_id
                    settings["default_model"] = _first_chat_model(models) or ""
                    save_settings(settings)
            except Exception as e:  # noqa: BLE001
                logger.warning("⚠️ cat seed: setting default model failed: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.warning("⚠️ cat seed: db write failed: %s", e)
        result["reason"] = f"db write failed: {e}"
    finally:
        db.close()

    result["endpoint_id"] = ep_id
    if result["reachable"]:
        logger.info("✅ cat seed: '%s' connected — %d models at %s",
                    CAT_ENDPOINT_NAME, result["models"], base)
    else:
        logger.info("🔍 cat seed: '%s' registered but cat not reachable at %s yet "
                    "(will auto-connect when it starts)", CAT_ENDPOINT_NAME, base)
    return result

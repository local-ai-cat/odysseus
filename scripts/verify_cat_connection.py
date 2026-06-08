#!/usr/bin/env python3
"""Verify the Local AI Cat companion sees the cat's live models end-to-end.

Compares the cat server's own model list (ground truth, OpenAI /v1/models)
against what odysseus exposes via /api/models, and asserts every cat model is
visible through odysseus. Use this to confirm the startup auto-seed
(src/cat_seed.py) actually wired the cat through.

Two modes:

  # Against an already-running odysseus (e.g. the desktop app on :7860)
  scripts/verify_cat_connection.py --odysseus http://127.0.0.1:7860 \
      --cat http://127.0.0.1:11434/v1

  # Self-contained: spin up a throwaway odysseus on an isolated DB, seed, check,
  # tear down. Needs the repo venv. (auth disabled, fresh data dir)
  scripts/verify_cat_connection.py --spawn

Exit code 0 = all cat models visible in odysseus; non-zero = mismatch/error.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def _get_json(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def cat_models(cat_base: str) -> list[str]:
    """Ground truth: the cat's own /v1/models ids."""
    data = _get_json(cat_base.rstrip("/") + "/models")
    return sorted(m["id"] for m in data.get("data", []))


def odysseus_models(odysseus_url: str) -> list[str]:
    """Every model id odysseus exposes through /api/models, flattened."""
    data = _get_json(odysseus_url.rstrip("/") + "/api/models?refresh=true", timeout=30)
    ids: set[str] = set()
    for item in data.get("items", []):
        for key in ("models", "models_extra"):
            ids.update(item.get(key, []) or [])
    return sorted(ids)


def _free_port(start: int = 7950) -> int:
    for p in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


def _spawn_odysseus(repo: str, cat_base: str):
    """Launch a throwaway odysseus on an isolated DB; return (proc, base_url)."""
    port = _free_port()
    tmp = tempfile.mkdtemp(prefix="odysseus-verify-")
    env = dict(os.environ)
    env.update(
        DATABASE_URL=f"sqlite:///{tmp}/app.db",
        AUTH_ENABLED="false",
        LOCALAI_CAT_BASE_URL=cat_base,
        FASTEMBED_CACHE_PATH=f"{tmp}/fastembed",
        CHROMADB_PATH=f"{tmp}/chroma",
        ANONYMIZED_TELEMETRY="False",
    )
    py = os.path.join(repo, "venv", "bin", "python")
    proc = subprocess.Popen(
        [py, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=repo, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/api/models", timeout=2)
            break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("odysseus exited during startup")
            time.sleep(1)
    return proc, base


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--odysseus", default="http://127.0.0.1:7860", help="running odysseus base URL")
    ap.add_argument("--cat", default="http://127.0.0.1:11434/v1", help="cat /v1 base URL")
    ap.add_argument("--spawn", action="store_true", help="spawn a throwaway odysseus on an isolated DB")
    args = ap.parse_args()

    try:
        cat = cat_models(args.cat)
    except Exception as e:
        print(f"❌ could not reach cat at {args.cat}: {e}")
        return 2
    print(f"🐱 cat exposes {len(cat)} models at {args.cat}")

    proc = None
    odysseus_url = args.odysseus
    try:
        if args.spawn:
            repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            print("🚀 spawning throwaway odysseus (isolated DB, auth off)…")
            proc, odysseus_url = _spawn_odysseus(repo, args.cat)
            print(f"   up at {odysseus_url}")

        try:
            ody = odysseus_models(odysseus_url)
        except Exception as e:
            print(f"❌ could not reach odysseus /api/models at {odysseus_url}: {e}")
            return 2
        print(f"😺 odysseus exposes {len(ody)} models at {odysseus_url}")

        missing = [m for m in cat if m not in ody]
        if missing:
            print(f"❌ {len(missing)} cat model(s) NOT visible in odysseus:")
            for m in missing:
                print("   -", m)
            return 1
        print(f"✅ all {len(cat)} cat models are visible through odysseus")
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Self-contained desktop launcher for Odysseus (PyInstaller-frozen).

Adapted from confnote's packages/local-app/desktop.py. Picks a free localhost
port, starts uvicorn against odysseus's `app:app` in a daemon thread, then opens
the UI (pywebview window if available, else the system browser).

Frozen-app specifics:
  * odysseus resolves BASE_DIR / STATIC_DIR / DATA_DIR from __file__ of
    core/constants.py and mounts static via the *relative* path "static".
    Under PyInstaller (onedir) everything lands in Contents/Resources, so we
    chdir there and put it on sys.path BEFORE importing the app.
  * The app writes to ./data and ./logs. Those are read-only inside a signed
    .app, so we redirect them to ~/Library/Application Support/Odysseus and
    seed the bundled data/ (incl. the cached FastEmbed ONNX model) on first run.
"""

import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path


def _resource_root() -> Path:
    # PyInstaller onedir: sys._MEIPASS is Contents/Resources (where --add-data
    # lands). From source: the repo root (parent of packaging/).
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return Path(__file__).resolve().parent.parent


ROOT = _resource_root()


def _writable_support_dir() -> Path:
    base = Path.home() / "Library" / "Application Support" / "Odysseus"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _seed_writable_data():
    """Move the app's mutable state out of the read-only bundle.

    odysseus hard-codes BASE_DIR = <repo>/, then DATA_DIR = BASE_DIR/data and
    writes app.db, logs, chroma, fastembed_cache there. Inside a signed .app
    that path is read-only. We seed a per-user copy and symlink data/ + logs/
    from the bundle to it so constants.py's relative paths still resolve.
    """
    support = _writable_support_dir()
    for sub in ("data", "logs"):
        src = ROOT / sub
        dst = support / sub
        if not dst.exists():
            if src.exists() and src.is_dir() and not src.is_symlink():
                shutil.copytree(src, dst, symlinks=True)
            else:
                dst.mkdir(parents=True, exist_ok=True)
        # Replace the (possibly read-only) bundle dir with a symlink to the
        # writable copy. Best-effort: if the bundle is read-only we can't, but
        # env overrides below still point most writers at the right place.
        try:
            if src.is_symlink() or src.exists():
                if src.is_symlink():
                    src.unlink()
                elif src.is_dir():
                    shutil.rmtree(src)
            src.symlink_to(dst)
        except OSError:
            pass
    # Belt-and-suspenders env overrides honored by odysseus/HF/fastembed.
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{support / 'data' / 'app.db'}")
    os.environ.setdefault("FASTEMBED_CACHE_PATH", str(support / "data" / "fastembed_cache"))
    os.environ.setdefault("HF_HOME", str(support / "data" / "hf_home"))
    # Embedded ChromaDB persists its vector store here. Leaving CHROMADB_HOST
    # unset keeps get_chroma_client() in embedded (PersistentClient) mode — no
    # server, no Docker. The dir must be writable, so it lives in App Support.
    chroma_dir = support / "chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("CHROMADB_PATH", str(chroma_dir))
    # ChromaDB phones home by default; a self-contained desktop app shouldn't.
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    os.environ.setdefault("CHROMA_TELEMETRY", "False")
    # Don't force a login for the local self-contained app.
    os.environ.setdefault("AUTH_ENABLED", "false")
    return support


def _free_port(start=7860):
    env_port = os.environ.get("ODYSSEUS_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    for p in range(start, start + 40):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


def _serve(port):
    import uvicorn

    # Import here, after chdir + env are set, so constants.py resolves paths
    # against the bundle. Pass the imported app object (string import would
    # re-import under uvicorn's reloader machinery).
    from app import app as fastapi_app

    uvicorn.run(fastapi_app, host="127.0.0.1", port=port, log_level="info")


def _idle():
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def _wait_until_up(port, timeout=60):
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as r:
                if r.status < 500:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    # constants.py + the StaticFiles("static") mount are relative to CWD/__file__
    # in the repo layout; make the bundle's Resources dir the working tree.
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    _seed_writable_data()

    port = _free_port()
    threading.Thread(target=_serve, args=(port,), daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    print(f"odysseus  ->  {url}  (root={ROOT})", flush=True)

    _wait_until_up(port)

    if os.environ.get("ODYSSEUS_NOGUI"):
        return _idle()

    try:
        import webview

        webview.create_window("Odysseus", url, width=1280, height=860, min_size=(900, 600))
        webview.start()
    except Exception as e:  # noqa: BLE001
        print(f"webview unavailable ({e}); opening in browser instead", flush=True)
        import webbrowser

        webbrowser.open(url)
        _idle()


if __name__ == "__main__":
    main()

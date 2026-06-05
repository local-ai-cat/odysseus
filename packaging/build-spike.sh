#!/bin/sh
# PROOF-OF-CONCEPT: freeze Odysseus into a self-contained macOS .app.
# Ad-hoc signed only (spike). Run from repo root or anywhere.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$DIR/.." && pwd)"
VENV="$REPO/venv"
NAME="Odysseus"

cd "$REPO"
rm -rf "$DIR/build" "$DIR/dist" "$DIR/$NAME.spec"

ICON=""
[ -f "$REPO/dist/Odysseus.app/Contents/Resources/odysseus.icns" ] && \
  ICON="--icon $REPO/dist/Odysseus.app/Contents/Resources/odysseus.icns"

"$VENV/bin/python" -m PyInstaller --noconfirm --clean --windowed \
  --name "$NAME" \
  --osx-bundle-identifier "com.spike.odysseus" \
  --distpath "$DIR/dist" --workpath "$DIR/build" --specpath "$DIR" \
  $ICON \
  --add-data "$REPO/static:static" \
  --add-data "$REPO/data:data" \
  --add-data "$REPO/config:config" \
  --collect-submodules core \
  --collect-submodules routes \
  --collect-submodules src \
  --collect-submodules services \
  --collect-submodules companion \
  --collect-submodules integrations \
  --collect-submodules mcp_servers \
  --collect-all uvicorn \
  --collect-all fastembed \
  --collect-all onnxruntime \
  --collect-all chromadb \
  --collect-all chromadb_rust_bindings \
  --collect-submodules kubernetes \
  --hidden-import chromadb_rust_bindings \
  --collect-all tokenizers \
  --collect-all huggingface_hub \
  --collect-data certifi \
  --hidden-import app \
  --hidden-import uvicorn.lifespan.on \
  --hidden-import uvicorn.lifespan.off \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.http.h11_impl \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.protocols.websockets.websockets_impl \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.loops.asyncio \
  packaging/desktop.py

echo "=== build done; app at $DIR/dist/$NAME.app ==="

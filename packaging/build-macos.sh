#!/bin/sh
# Build a self-contained, double-clickable Odysseus.app with PyInstaller.
#
#   packaging/build-macos.sh              # PROD → "Odysseus.app"      (lean)
#   packaging/build-macos.sh dev [tag]    # DEV  → "Odysseus dev.app"  (full, +tests)
#
# Dev and prod have different names + bundle ids, so you can install and run
# BOTH side by side (test prod while iterating on dev). Dev bundle ids include a
# build tag to force a fresh macOS permission identity.
#
# DEV  vs  PROD payload (the "keep tests in dev, trim prod" split):
#   • kubernetes is excluded from BOTH builds. chromadb only imports it from its
#     *distributed* segment directory — never in the embedded PersistentClient
#     mode this app uses — so it is dead weight everywhere.
#   • DEV  additionally bundles the tests/ tree (+ pyproject.toml + pytest) so the
#          frozen bundle is self-testable:  "Odysseus dev" --run-tests
#   • PROD strips tests/. It is never imported at runtime; the shipped app stays
#          lean and `make test` (repo venv) remains the canonical full-green run.
#
# Developer ID signed by default so macOS sees the real app identity. Set
# ALLOW_ADHOC=1 for throwaway local builds on machines without the cert.
# Override the identity with ODYSSEUS_SIGN_ID. NOTARIZE=1 staples for other Macs.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$DIR/.." && pwd)"
VENV="$REPO/venv"

sanitize_bundle_tag() {
  tag="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-+/-/g')"
  [ -n "$tag" ] || tag="local"
  case "$tag" in
    [a-z]*) ;;
    *) tag="b$tag" ;;
  esac
  printf '%s' "$tag"
}

default_dev_tag() {
  branch="$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'local')"
  sha="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || printf 'nosha')"
  stamp="$(date +%Y%m%d%H%M%S)"
  printf '%s-%s-%s' "$branch" "$sha" "$stamp"
}

if [ "$1" = "dev" ]; then
  MODE="dev"
  DEV_TAG_RAW="${ODYSSEUS_DEV_TAG-${2-}}"
  [ -n "$DEV_TAG_RAW" ] || DEV_TAG_RAW="$(default_dev_tag)"
  DEV_TAG="$(sanitize_bundle_tag "$DEV_TAG_RAW")"
  NAME="Odysseus dev"; BID="com.atlas.odysseus.dev.$DEV_TAG"
else
  MODE="prod"
  NAME="Odysseus"; BID="com.atlas.odysseus"
fi

[ -x "$VENV/bin/python" ] || { echo "venv missing at $VENV — run: python3.11 -m venv venv && venv/bin/pip install -r requirements.txt" >&2; exit 1; }
"$VENV/bin/python" -m pip -q install pyinstaller pywebview >/dev/null 2>&1 || true

# Icon (best effort) — reuse the spike's .icns if present, else derive from jpg.
ICON=""
ICNS="$DIR/odysseus.icns"
if [ ! -f "$ICNS" ] && [ -f "$REPO/docs/odysseus.jpg" ] && command -v sips >/dev/null 2>&1; then
  TMPIMG="$(mktemp -d)"
  sips -s format icns "$REPO/docs/odysseus.jpg" --out "$ICNS" >/dev/null 2>&1 || true
  rm -rf "$TMPIMG"
fi
[ -f "$ICNS" ] && ICON="--icon $ICNS"

cd "$REPO"
rm -rf "$DIR/build" "$DIR/dist/$NAME.app" "$DIR/$NAME.spec"

# ── Payload split: kubernetes excluded everywhere; tests are dev-only ──
# Excluding kubernetes stops chromadb's PyInstaller hook from pulling the
# kubernetes client (never imported in embedded mode) and keeps builds fast.
PAYLOAD_FLAGS="--exclude-module kubernetes"
if [ "$MODE" = "dev" ]; then
  # Ship the test tree + config + pytest (and pytest-asyncio metadata so the
  # async markers register) so the frozen bundle is self-testable.
  PAYLOAD_FLAGS="$PAYLOAD_FLAGS --add-data $REPO/tests:tests --add-data $REPO/pyproject.toml:. \
    --hidden-import pytest --collect-all pytest_asyncio --copy-metadata pytest_asyncio"
else
  PAYLOAD_FLAGS="$PAYLOAD_FLAGS --exclude-module tests"
fi

# shellcheck disable=SC2086
"$VENV/bin/python" -m PyInstaller --noconfirm --clean --windowed \
  --name "$NAME" \
  --osx-bundle-identifier "$BID" \
  --distpath "$DIR/dist" --workpath "$DIR/build" --specpath "$DIR" \
  $ICON \
  $PAYLOAD_FLAGS \
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
  --hidden-import chromadb_rust_bindings \
  --collect-all tokenizers \
  --collect-all huggingface_hub \
  --collect-data certifi \
  --collect-all webview \
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

APPP="$DIR/dist/$NAME.app"
echo "built: $APPP ($(du -sh "$APPP" | cut -f1))"

# ── Code signing (Developer ID, hardened runtime + entitlements) ──
SIGN_ID="${ODYSSEUS_SIGN_ID-Developer ID Application: Atlas Codes LTD (599WAZ6282)}"
ENT="$DIR/entitlements.plist"
if [ -n "$SIGN_ID" ] && security find-identity -v -p codesigning 2>/dev/null | grep -qF "$SIGN_ID"; then
  echo "signing: $SIGN_ID (hardened runtime + entitlements)"
  TS=""
  [ -n "$NOTARIZE" ] && TS="--timestamp"
  codesign --force --deep --options runtime $TS --entitlements "$ENT" --sign "$SIGN_ID" "$APPP"
  codesign --verify --verbose=1 "$APPP" 2>&1 | tail -1
else
  if [ -z "$ALLOW_ADHOC" ]; then
    echo "Developer ID signing identity not available: '$SIGN_ID'" >&2
    echo "Install the Developer ID cert or rerun with ALLOW_ADHOC=1 for a throwaway local build." >&2
    exit 1
  fi
  [ -n "$NOTARIZE" ] && { echo "notarization requires a Developer ID identity; missing '$SIGN_ID'" >&2; exit 1; }
  echo "signing: ad-hoc (no '$SIGN_ID' identity found)"
  codesign --force --deep --options runtime --entitlements "$ENT" --sign - "$APPP" 2>/dev/null || true
fi

# ── Notarization (opt-in: NOTARIZE=1) ──
if [ -n "$NOTARIZE" ]; then
  PROFILE="${ODYSSEUS_NOTARY_PROFILE:-odysseus-notary}"
  ZIP="$DIR/dist/$NAME-notarize.zip"
  ditto -c -k --keepParent "$APPP" "$ZIP"
  set +e
  if [ -n "$APPLE_ID" ] && [ -n "$APPLE_TEAM_ID" ] && [ -n "$APPLE_APP_PASSWORD" ]; then
    echo "notarizing via APPLE_ID/APPLE_TEAM_ID/APPLE_APP_PASSWORD…"
    xcrun notarytool submit "$ZIP" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" --wait
    NOTARY_RC=$?
  else
    echo "notarizing via keychain profile '$PROFILE'…"
    xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait
    NOTARY_RC=$?
  fi
  set -e
  if [ "$NOTARY_RC" -eq 0 ]; then
    xcrun stapler staple "$APPP" && echo "notarized + stapled ✓"
  else
    echo "notarization FAILED — inspect with: xcrun notarytool log <submission-id> ..." >&2
    rm -f "$ZIP"; exit 1
  fi
  rm -f "$ZIP"
fi

cat <<EOF

Built: $APPP
Bundle ID: $BID
Mode: $MODE $( [ "$MODE" = dev ] && printf '(tests + kubernetes bundled)' || printf '(trimmed: no tests, no kubernetes)' )

Run it:
  open "$APPP"
  # or headless: ODYSSEUS_NOGUI=1 "$APPP/Contents/MacOS/$NAME"

Notes:
 • DEV and PROD are separate apps — build both side by side:
     packaging/build-macos.sh         # prod (lean)
     packaging/build-macos.sh dev     # dev  (+tests, fresh permission identity per build)
   Pin a dev tag with ODYSSEUS_DEV_TAG=<tag> to reuse a permission set.
 • Run the in-bundle test suite (dev only):
     "$APPP/Contents/MacOS/$NAME" --run-tests        # all bundled tests
     "$APPP/Contents/MacOS/$NAME" --run-tests -q -k smoke   # pytest args pass through
   (prod is trimmed — it prints a notice and exits; use \`make test\` on the repo.)
 • Distribute to other Macs = Developer ID + notarization:
     NOTARIZE=1 packaging/build-macos.sh
EOF

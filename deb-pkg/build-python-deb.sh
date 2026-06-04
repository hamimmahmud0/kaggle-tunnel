#!/bin/bash
# Build python3-kaggle-tunnel Debian package
#
# Usage:
#   bash deb-pkg/build-python-deb.sh
#
# This creates deb-pkg/python3-kaggle-tunnel.deb which installs the
# kaggle_tunnel Python module to /usr/lib/python3/dist-packages/.
#
# Install with:
#   sudo dpkg -i deb-pkg/python3-kaggle-tunnel.deb
#
# Verify with:
#   python3 -c "from kaggle_tunnel.app import generate_tunnelbroker_cell_code; print('OK')"

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PKG_DIR="$SCRIPT_DIR/python3-kaggle-tunnel"
DIST_PYTHON="$PKG_DIR/usr/lib/python3/dist-packages"

# ── Clean previous build artifacts ──────────────────────────────────
rm -rf "$DIST_PYTHON/kaggle_tunnel"

# ── Copy the Python source into the package ─────────────────────────
echo "Copying kaggle_tunnel Python module..."
mkdir -p "$DIST_PYTHON/kaggle_tunnel"
cp -r "$PROJECT_DIR/src/kaggle_tunnel/"* "$DIST_PYTHON/kaggle_tunnel/"

# ── Clean up __pycache__ and .pyc files ─────────────────────────────
find "$DIST_PYTHON" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
find "$DIST_PYTHON" -name '*.pyc' -delete

# ── Set proper permissions ──────────────────────────────────────────
find "$PKG_DIR" -type f -name '*.py' -exec chmod 644 {} +
find "$PKG_DIR" -type d -exec chmod 755 {} +
chmod 755 "$DIST_PYTHON/kaggle_tunnel/bin/cloudflared" 2>/dev/null || true

# ── Build the .deb ──────────────────────────────────────────────────
echo "Building python3-kaggle-tunnel.deb..."
dpkg-deb --build --root-owner-group "$PKG_DIR" "$SCRIPT_DIR/python3-kaggle-tunnel.deb"

echo "Done! Created: $SCRIPT_DIR/python3-kaggle-tunnel.deb"
echo ""
echo "Install with: sudo dpkg -i deb-pkg/python3-kaggle-tunnel.deb"

#!/usr/bin/env bash
#
# setup.sh
#  - Installs http-server globally via npm
#  - Installs any client-side node modules (if package.json exists under client/)
#  - Creates a Python virtual environment and installs server dependencies
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#

set -e

# ─── 1) Check prerequisites ──────────────────────────────────────────────────────────
echo "🔍 Checking for required tools..."

# Check for Node.js / npm
if ! command -v npm >/dev/null 2>&1; then
  echo "❌ npm not found. Please install Node.js (which includes npm) before proceeding."
  exit 1
fi

# Check for Python3
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 not found. Please install Python 3 before proceeding."
  exit 1
fi

# Check for pip (within python3)
if ! python3 -m pip --version >/dev/null 2>&1; then
  echo "❌ pip for python3 not found. Ensure pip is installed for your Python 3 environment."
  exit 1
fi

echo "✔️  Prerequisites satisfied."

# ─── 2) Install http-server globally ─────────────────────────────────────────────────
echo
echo "📦 Installing http-server globally (via npm)..."
npm install -g http-server
echo "✔️  http-server installed."

# ─── 3) Install client-side node modules ──────────────────────────────────────────────
CLIENT_DIR="$(pwd)/client"
if [ -d "$CLIENT_DIR" ]; then
  if [ -f "$CLIENT_DIR/package.json" ]; then
    echo
    echo "📂 Installing client-side node modules (cd client && npm install)..."
    pushd "$CLIENT_DIR" >/dev/null
    npm install
    popd >/dev/null
    echo "✔️  Client node modules installed."
  else
    echo
    echo "ℹ️  No package.json found in client/, skipping npm install there."
  fi
else
  echo
  echo "⚠️  client/ directory not found; skipping client-side node modules installation."
fi

# ─── 4) Create Python virtual environment ─────────────────────────────────────────────
VENV_DIR="$(pwd)/venv"
if [ -d "$VENV_DIR" ]; then
  echo
  echo "ℹ️  Virtual environment already exists at venv/; skipping creation."
else
  echo
  echo "🐍 Creating Python 3 virtual environment in venv/..."
  python3 -m venv venv
  echo "✔️  Virtual environment created."
fi

# ─── 5) Activate venv and install server requirements ─────────────────────────────────
echo
echo "⚙️  Activating virtual environment and installing server dependencies..."
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

SERVER_DIR="$(pwd)/server"
REQ_FILE="$SERVER_DIR/requirements.txt"
if [ -f "$REQ_FILE" ]; then
  pip install --upgrade pip
  pip install -r "$REQ_FILE"
  echo "✔️  Server dependencies installed from requirements.txt."
else
  echo "⚠️  requirements.txt not found in server/, skipping pip install."
fi

# ─── 6) Final message ────────────────────────────────────────────────────────────────
echo
echo "🎉 Setup complete!"
echo " • http-server global installation:   $(command -v http-server)"
echo " • Virtual environment:               $VENV_DIR"
if [ -f "$REQ_FILE" ]; then
  echo " • Server requirements installed from $REQ_FILE"
fi
if [ -d "$CLIENT_DIR/package.json" ]; then
  echo " • Client node modules installed in $CLIENT_DIR"
fi

echo
echo "You can now run:"
echo "  1) Start the client:  cd client && http-server -S -C ../server/cert.pem -K ../server/key.pem -p 8443"
echo "  2) Start the server:  source venv/bin/activate && cd server && python3 server.py cert.pem key.pem --bind-address 0.0.0.0 --bind-port 4433"
echo "  3) Launch Chrome with SPKI fingerprint: see instructions above."

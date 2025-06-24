#!/usr/bin/env bash
#
# start.sh by Rudrashis Gorai
#  - If server/cert.pem and server/key.pem do not exist, generate a self-signed pair.
#  - Compute and export the SPKI fingerprint (Base64) into $FINGERPRINT (and to spki_fingerprint.txt).
#  - Start the static HTTPS client (http-server on port 8443).
#  - Start the Python WebTransport/WebRTC server (server.py on port 4433).
#  - Launch Google Chrome with QUIC enabled and trusting our self-signed SPKI fingerprint.
#

set -e

# ─── 1) Determine project root and server directory ───────────────────────────────
BASEDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$BASEDIR/server"
CLIENT_DIR="$BASEDIR/client"

# ─── 2) Ensure cert.pem + key.pem exist under server/ ───────────────────────────────
if [ ! -f "$SERVER_DIR/cert.pem" ] || [ ! -f "$SERVER_DIR/key.pem" ]; then
  echo "🔐 server/cert.pem or server/key.pem not found. Generating a new self-signed pair…"
  openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
    -keyout "$SERVER_DIR/key.pem" \
    -out "$SERVER_DIR/cert.pem" \
    -subj "/CN=localhost" \
    -addext "subjectAltName = DNS:localhost"
  echo "✅ Generated server/key.pem and server/cert.pem."
fi

# ─── 3) Compute the SPKI fingerprint (Base64) from server/cert.pem ─────────────────
FINGERPRINT=$(
  openssl x509 -in "$SERVER_DIR/cert.pem" -noout -pubkey \
    | openssl pkey -pubin -outform der \
    | openssl dgst -sha256 -binary \
    | openssl base64
)
# Save it for manual inspection if needed
echo "$FINGERPRINT" > "$BASEDIR/spki_fingerprint.txt"
echo "🔑 SPKI fingerprint (also saved to spki_fingerprint.txt):"
echo "   $FINGERPRINT"
export FINGERPRINT

# ─── 4) Start the static HTTPS client with http-server on port 8443 ───────────────
cd "$CLIENT_DIR"
echo "▶️  Starting static client at https://localhost:8443 (serving $CLIENT_DIR)…"
http-server -S -C "$SERVER_DIR/cert.pem" -K "$SERVER_DIR/key.pem" -p 8443 &
CLIENT_PID=$!
echo "$CLIENT_PID" > "$BASEDIR/.client.pid"
cd "$BASEDIR"

# ─── 5) Start the Python WebTransport/WebRTC server on port 4433 ───────────────────
echo "▶️  Starting WebTransport/WebRTC server at https://0.0.0.0:4433…"
python3 "$SERVER_DIR/server.py" "$SERVER_DIR/cert.pem" "$SERVER_DIR/key.pem" &
SERVER_PID=$!
echo "$SERVER_PID" > "$BASEDIR/.server.pid"

# ─── 6) Give the servers a moment to spin up ────────────────────────────────────
sleep 1

# ─── 7) Launch Chrome with QUIC with my self-signed certificate ────────────────────
echo "▶️  Launching Chrome…"
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --user-data-dir="$HOME/temporary-chrome-profile" \
  --ignore-certificate-errors-spki-list="$FINGERPRINT" \
  --origin-to-force-quic-on=localhost:4433 \
  "https://localhost:8443/index.html" &
CHROME_PID=$!
echo "$CHROME_PID" > "$BASEDIR/.chrome.pid"

# ─── 8) Summary ────────────────────────────────────────────────────────────────────
echo
echo "✅  Done. Processes started:"
echo "    • Client (http-server) PID = $CLIENT_PID"
echo "    • Server (server.py)   PID = $SERVER_PID"
echo "    • Chrome               PID = $CHROME_PID"
echo
echo "   To stop everything, run: ./stop.sh"

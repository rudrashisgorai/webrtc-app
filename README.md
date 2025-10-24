#  Ball WebTransport+WebRTC Project

<img width="1064" height="597" alt="Screenshot 2025-10-24 at 6 13 30 AM" src="https://github.com/user-attachments/assets/052e7c93-380e-4c3a-911a-d52431879e13" />

## Overview
This repository implements a simple interactive demo where a server continuously generates 2D frames of a green bouncing ball and streams those frames (H.264-encoded) to a browser client over WebRTC. In parallel, the browser client analyzes each incoming frame, extracts the ball’s (x, y) coordinates, and sends those coordinates back to the server. The server calculates a real-time error between the detected coordinates and the ground truth, then sends that error back to the browser. All control signaling (SDP offers/answers, ICE candidates) flows over WebTransport (HTTP/3 + QUIC), and video streaming uses WebRTC (PeerConnection).

---


- **`client/`**  
  Contains a static web client (`index.html` + `client.js`) that runs in the browser. It:
  1. Establishes a WebTransport connection (`WebTransport("https://localhost:4433/webtransport")`).
  2. Negotiates a WebRTC PeerConnection with no external ICE servers (server is the only peer).
  3. Sends its SDP offer over a WebTransport unidirectional stream.  
  4. Receives the SDP answer (over WebTransport), sets `setRemoteDescription`.
  5. Renders the incoming H.264-encoded video on a `<video>` element.  
  6. On each video frame (detected via `requestAnimationFrame` after `<video>` is playing), extracts the green ball’s center by sampling pixel data from a hidden `<canvas>`.  
  7. Sends detected `(x, y)` coords back to server via WebTransport datagrams.  
  8. Listens for “error” datagrams from server and displays real-time pixel-error on screen.

- **`server/`**  
  Contains the Python asyncio-based server that:
  1. Listens for WebTransport (HTTP/3 + QUIC) connections on port 4433 using `aioquic`.  
  2. When a `CONNECT /webtransport` handshake arrives, spins up a new `SessionHandler(session_id, H3Connection, loop)`.  
  3. `SessionHandler` listens for incoming WebTransport events:
     - **DatagramReceived**: parse JSON → if `"type":"ice-candidate"`, feed into `RTCPeerConnection.addIceCandidate()`; if `"type":"coords"`, compute error vs. `BouncingBallGenerator.get_position()` and respond with `{"type":"error","e":<value>}` over WebTransport datagram.
     - **WebTransportStreamDataReceived** on a unidirectional stream: parse SDP offer, start a `BouncingBallGenerator(thread)`, create an `aiortc.RTCPeerConnection` with `RTCConfiguration(iceServers=[])`, attach a `BouncingBallMediaTrack(generator)` (H.264), set remote description, create answer, set local description, immediately send JSON answer back on a new WebTransport unidirectional stream.
  4. `BouncingBallGenerator`: a background `threading.Thread` that repeatedly (frame‐rate configurable) draws a green ball on a blank NumPy array and optionally saves each frame to `saved_frames/` if `save_frames=True`. Exposes `get_frame()` and `get_position()`.  
  5. `BouncingBallMediaTrack`: a subclass of `aiortc.VideoStreamTrack` whose `recv()` pulls the latest NumPy frame from `BouncingBallGenerator`, wraps it in an `av.VideoFrame`, and sends it to the WebRTC pipeline (H.264 encoding handled by aiortc’s internal encoder).

- **`tests/`**  
  - **`test_server.py`**:  unit tests for `BouncingBallGenerator` and `BouncingBallMediaTrack`.    

- **`start.sh`** / **`stop.sh`**  
  Shell scripts to automate:
  - Certificate creation (if missing), SPKI fingerprint extraction, HTTP‐server for client on port 8443, Python server on port 4433, launching Chrome with the correct flags to trust the local SPKI and force QUIC for `localhost:4433`.


---

## Design Decisions

1. **WebTransport for Signaling**  
   - All SDP and ICE candidate exchanges occur over WebTransport (HTTP/3 datagrams & unidirectional streams). We deliberately avoid opening a separate WebSocket or long‐polling channel.  
   - WebTransport unidirectional streams carry the SDP JSON payloads. WebTransport datagrams carry small JSON messages (ICE candidates, `(x, y)` coords, error values).  
   - Advantage: single QUIC connection handles both control and data.


2. **H.264 Encoding**  
   - aiortc defaults to VP8/VP9 if available, but many browsers prefer H.264. We “prefer H264” in SDP by rewriting the `m=video` payload order.  
   - The track wrapper itself is codec‐agnostic; aiortc’s built‐in encoder will pick H.264 if the SDP indicates it’s first.

3. **Generator + MediaTrack Separation**  
   - A dedicated `BouncingBallGenerator(threading.Thread)` continuously produces raw frames at a given FPS.  
   - `BouncingBallMediaTrack` simply pulls from that thread’s latest frame on each `recv()` call. This allows `recv()` to block on `next_timestamp()` until the next frame boundary, preserving smooth playback.

4. **Coordinate Detection on Client**  
   - We draw each `<video>` frame into a hidden `<canvas>` and sample pixels in e.g. 4×4 steps to locate bright‐green pixels (`g > 200 && r < 50 && b < 50`).  
   - Averaging all detected bright‐green pixels yields the ball center. This is fast enough at 640×480, and sampling at lower resolution (step=4) reduces CPU.

5. **Error Computation**  
   - The client sends back `(x, y)` coords once per animation frame (`requestAnimationFrame`). The server fetches its ground‐truth from `generator.get_position()` and computes `sqrt((x_gt - x_client)^2 + (y_gt - y_client)^2)`.  
   - That error travels as a JSON datagram back to the client and is displayed in real‐time. Note: there will be some latency, so the measured error includes network/encoding delays.  

6. **Thread vs. asyncio**  
   - The generator is a dedicated thread because synchronous OpenCV drawing and `time.sleep()` are simplest in a thread.  
   - The server’s main loop is asyncio‐based (`aioquic`, `aiortc`, event loop). We simply let the generator thread run in parallel.  

7. **Certificate & SPKI Handling**  
   - `start.sh` checks if `server/cert.pem` & `server/key.pem` exist; if not, it auto‐generates a self‐signed cert with `openssl req -x509 … -addext "subjectAltName = DNS:localhost"`.  
   - We compute the Base64‐encoded SPKI fingerprint as:  
     ```bash
     openssl x509 -in cert.pem -noout -pubkey        | openssl pkey -pubin -outform der        | openssl dgst -sha256 -binary        | openssl base64
     ```  
   - Chrome is launched with `--ignore-certificate-errors-spki-list=$FINGERPRINT` and `--origin-to-force-quic-on=localhost:4433` so that QUIC (HTTP/3) accepts our local SPKI.

---

## Getting Started

### Prerequisites

- **Node.js (v14+)** with `http-server` installed globally, or installed via `npm install`.
- **Python 3.8+**  
  - `pip install -r server/requirements.txt` (contains `aioquic`, `aiortc`, `opencv-python`, `numpy`, etc.)

### Manual Setup

1. **Certificates**  
   In `server/`:
   ```bash
   cd server
   mkdir -p server
   # If cert+key missing:
   openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
     -keyout key.pem -out cert.pem -subj "/CN=localhost" \
     -addext "subjectAltName = DNS:localhost"
   ```

2. **Compute SPKI fingerprint**  
   ```bash
   openssl x509 -in cert.pem -noout -pubkey      | openssl pkey -pubin -outform der      | openssl dgst -sha256 -binary      | openssl base64 > ../spki_fingerprint.txt
   ```

3. **Start HTTP‐server for client**  
   ```bash
   cd ../client
   http-server -S -C ../server/cert.pem -K ../server/key.pem -p 8443
   ```

4. **Start Python WebTransport/WebRTC server**  
   ```bash
   cd ../server
   python3 server.py cert.pem key.pem
   ```

5. **Launch Chrome**  
   ```bash
   export FINGERPRINT=$(<../spki_fingerprint.txt)
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
     --user-data-dir="$HOME/tmp-chrome-profile" \
     --ignore-certificate-errors-spki-list="$FINGERPRINT" \
     --origin-to-force-quic-on=localhost:4433 \
     https://localhost:8443/index.html
   ```

### Automated `setup.sh / start.sh` / `stop.sh`

- `setup.sh` http-server globally via npm, client-side node modules and creates a Python virtual environment and installs server dependencies
- `start.sh` does all of the above in one command, auto‐generating certificates and SPKI if missing.
- `stop.sh` reads stored PIDs (`.client.pid`, `.server.pid`, `.chrome.pid`) and kills those processes.


---

## Testing

1. **Install test dependencies**:  
   ```bash
   pip install pytest numpy pytest-asyncio
   ```
2. **Run unit tests**:  
   ```bash
   pytest -q
   ```
   - `test_generator_emits_frame_and_position_changes` Verifies that the BouncingBallGenerator produces a frame within 0.5 s at a given FPS and that its reported ball position changes after one frame interval.
   - `test_media_track_recv_returns_video_frame` Ensures that wrapping a manually seeded BouncingBallGenerator in a BouncingBallMediaTrack yields a black av.VideoFrame of the expected width and height when recv() is called.




---


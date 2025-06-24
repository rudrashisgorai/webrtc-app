

#!/usr/bin/env python3
# By Rudrashis Gorai
import argparse
import asyncio
import json
import logging
import math
import os
import signal
import ssl
import threading
import time
import uuid
from collections import defaultdict
from typing import Dict
from aiortc import VideoStreamTrack

import cv2
import numpy as np
from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import (
    DatagramReceived,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import stream_is_unidirectional
from aioquic.quic.events import ProtocolNegotiated, QuicEvent, StreamReset

from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCRtpTransceiver,
    RTCPeerConnection, RTCConfiguration
)

from av import VideoFrame

logger = logging.getLogger("bouncing_server")

import os
import cv2
import numpy as np
import threading
import time

class BouncingBallGenerator(threading.Thread):
    """
    Thread that continuously generates a 640×480 BGR frame with a green bouncing ball.
    Exposes get_frame() → latest NumPy array, and get_position() → (x, y).
    """

    def __init__(self, width: int = 640, height: int = 480, fps: int = 30, save_frames: bool = False):
        super().__init__()
        self.width = width
        self.height = height
        self.fps = fps
        self.interval = 1.0 / fps

        # Ball state
        self.x = width // 2
        self.y = height // 2
        self.vx = 5
        self.vy = 3
        self.radius = 20

        self.lock = threading.Lock()
        self._frame = None
        self._running = True

        # If True, write each frame as a PNG on disk
        self.save_frames = save_frames

        # Create an output directory (if it doesn't exist)
        if self.save_frames:
            self._out_dir = os.path.join(os.getcwd(), "saved_frames")
            os.makedirs(self._out_dir, exist_ok=True)
            self._frame_count = 0

    def run(self):
        while self._running:
            # 1) Create blank frame and draw the green ball
            frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            cv2.circle(frame, (int(self.x), int(self.y)), self.radius, (0, 255, 0), -1)

            # 2) If saving is enabled, write this frame to disk
            if self.save_frames:
                filename = f"frame_{self._frame_count:05d}.png"
                filepath = os.path.join(self._out_dir, filename)
                cv2.imwrite(filepath, frame)
                # Optionally log to confirm disk write
                print(f"[SERVER DEBUG] Saved frame #{self._frame_count} → {filepath}")
                self._frame_count += 1

            # 3) Update ball position
            self.x += self.vx
            self.y += self.vy
            if self.x <= self.radius or self.x >= self.width - self.radius:
                self.vx *= -1
            if self.y <= self.radius or self.y >= self.height - self.radius:
                self.vy *= -1

            # 4) Store a copy of the frame in a thread‐safe way
            with self.lock:
                self._frame = frame.copy()
                self._pos = (self.x, self.y)

            # 5) Sleep until the next frame time
            time.sleep(self.interval)

    def get_frame(self):
        with self.lock:
            return self._frame.copy() if self._frame is not None else None

    def get_position(self):
        with self.lock:
            return getattr(self, "_pos", (self.x, self.y))

    def stop(self):
        self._running = False


# -----------------------------
# MediaStreamTrack for aiortc
# -----------------------------
class BouncingBallTrack(VideoFrame):
    """
    A simple wrapper (not strictly needed). We’ll implement our own track below.
    """
    pass



class BouncingBallMediaTrack:
    """
    A VideoStreamTrack that pulls frames from BouncingBallGenerator and wraps them as VideoFrame.
    """

    def __init__(self, generator: BouncingBallGenerator):
        class _Track(VideoStreamTrack):
            """
            Subclass VideoStreamTrack so that next_timestamp() is available.
            """

            def __init__(self, gen):
                super().__init__()  # VideoStreamTrack.__init__ sets up next_timestamp()
                self.generator = gen

            async def recv(self):
                # VideoStreamTrack.next_timestamp() is now available
                # logger.info(f"[SERVER DEBUG] yoyo BouncingBallMediaTrack.recv() called at {time.time()}")

                pts, time_base = await self.next_timestamp()
                frame_bgr = self.generator.get_frame()
                if frame_bgr is None:
                    # If generator isn't ready yet, send a black frame
                    h, w = self.generator.height, self.generator.width
                    arr = np.zeros((h, w, 3), dtype=np.uint8)
                    av_frame = VideoFrame.from_ndarray(arr, format="bgr24")
                else:
                    av_frame = VideoFrame.from_ndarray(frame_bgr, format="bgr24")
                av_frame.pts = pts
                av_frame.time_base = time_base
                return av_frame

        self.track = _Track(generator)




# -----------------------------
# Session Handler for WebTransport
# -----------------------------
class SessionHandler:
    """
    Handles a single WebTransport session:
      1. Receives the client’s SDP offer over a WebTransport unidirectional stream.
      2. Spins up a BouncingBallGenerator thread and creates an aiortc RTCPeerConnection.
      3. Attaches a custom BouncingBallMediaTrack to send H.264‐encoded frames.
      4. Exchanges ICE candidates with the client via WebTransport datagrams.
      5. Sends the SDP answer back on a new unidirectional stream (immediately after setLocalDescription).
      6. Receives “coords” datagrams from the client, computes real‐time error vs. generator position, and replies with “error” datagrams.
      7. Cleans up (stops generator, closes PeerConnection) when the connection closes or fails.
    """

    def __init__(self, session_id: int, http: H3Connection, loop: asyncio.AbstractEventLoop):
        self._session_id = session_id
        self._http = http
        self._loop = loop

        # Buffer partial WebTransport stream data by stream_id
        self._buffers: Dict[int, bytearray] = defaultdict(bytearray)

        # Create a PeerConnection that only gathers host candidates (no STUN/TURN)
        rtc_config = RTCConfiguration(iceServers=[])
        self.pc: RTCPeerConnection = RTCPeerConnection(rtc_config)

        # The generator will be started later when we receive an offer
        self.generator: BouncingBallGenerator = None


    def h3_event_received(self, event):
        # 1) Handle incoming WebTransport datagrams (ICE candidates or coords)
        if isinstance(event, DatagramReceived):
            try:
                msg = json.loads(event.data.decode("utf-8"))
            except Exception:
                return

            msg_type = msg.get("type")
            if msg_type == "ice-candidate":
                # Add the client’s ICE candidate to the RTCPeerConnection
                candidate = msg["candidate"]
                print("[DEBUG] Received remote ICE candidate from client:", candidate)  # <---

                asyncio.ensure_future(
                    self.pc.addIceCandidate(candidate),
                    loop=self._loop
                )

            elif msg_type == "coords":
                x_client = msg.get("x")
                y_client = msg.get("y")
                if self.generator:
                    x_gt, y_gt = self.generator.get_position()
                    dx = x_gt - x_client
                    dy = y_gt - y_client
                    error = math.hypot(dx, dy)
                    payload = json.dumps({"type": "error", "e": error}).encode("utf-8")
                    self._http.send_datagram(self._session_id, payload)

            return

        # 2) Handle incoming WebTransport unidirectional streams (SDP offer)
        if isinstance(event, WebTransportStreamDataReceived):
            stream_id = event.stream_id
            self._buffers[stream_id] += event.data
            if event.stream_ended:
                data = bytes(self._buffers.pop(stream_id))
                try:
                    msg = json.loads(data.decode("utf-8"))
                except Exception:
                    return

                if msg.get("type") == "offer":
                    print("[DEBUG] Received SDP offer from client")  # <--- debug
                    sdp_offer = msg["sdp"]
                    asyncio.ensure_future(
                        self._handle_offer(sdp_offer),
                        loop=self._loop
                    )

            return

        # 3) Handle stream resets (cleanup)
        if isinstance(event, StreamReset):
            sid = event.stream_id
            if sid in self._buffers:
                del self._buffers[sid]

    async def _handle_offer(self, sdp_offer: str):
        print(f"[DEBUG] _handle_offer() starting for session {self._session_id}")  # <---

        # 1. Start the bouncing‐ball generator thread
        self.generator = BouncingBallGenerator(width=640, height=480, fps= 30)
        self.generator.start()

        # 2. Create RTCPeerConnection
        self.pc = RTCPeerConnection()
        print(f"[DEBUG] Created RTCPeerConnection: {self.pc}")  # <---
        pc_id = f"PeerConnection({uuid.uuid4()})"
        logger.info(f"{pc_id} Creating PC for WebTransport session {self._session_id}")

        # 3. When aiortc gathers a new ICE candidate, send it via WebTransport datagram
        @self.pc.on("icecandidate")
        def on_icecandidate(event):
            if event.candidate:
                print("[DEBUG] New local ICE candidate:", event.candidate)  # <---
                cand_msg = {
                    "type": "ice-candidate",
                    "candidate": event.candidate.toJSON(),
                }
                self._http.send_datagram(
                    self._session_id,
                    json.dumps(cand_msg).encode("utf-8")
                )
        # def on_icecandidate(event):
        #     if event.candidate:
        #         c = event.candidate.toJSON()
        #         # Overwrite the container‐internal IP with the host‐published port:
        #         c["address"] = "127.0.0.1"
        #         c["port"]    = 4433
        #         self._http.send_datagram(self._session_id, json.dumps({
        #             "type": "ice-candidate",
        #             "candidate": c
        #         }).encode("utf-8"))

        

        # 4. Add the bouncing‐ball media track (H.264) to this PeerConnection
        track_wrapper = BouncingBallMediaTrack(self.generator)
        self.pc.addTrack(track_wrapper.track)

        # 5. Set the client’s SDP offer as remote description
        await self.pc.setRemoteDescription(
            RTCSessionDescription(sdp=sdp_offer, type="offer")
        )

        # 6. Create the answer and set the local description (once)
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)

        # 7. Immediately send that SDP answer back over a new WebTransport unidirectional stream
        answer_payload = json.dumps({
            "type": "answer",
            "sdp": self.pc.localDescription.sdp
        }).encode("utf-8")
        sid = self._http.create_webtransport_stream(
            self._session_id, is_unidirectional=True
        )
        self._http._quic.send_stream_data(sid, answer_payload, end_stream=True)

        # 8. Monitor connection state; clean up on "failed" or "closed"
        @self.pc.on("connectionstatechange")
        async def on_conn_state():
            logger.info(f"{pc_id} Connection state: {self.pc.connectionState}")
            if self.pc.connectionState in ("failed", "closed"):
                await self._cleanup()

    async def _cleanup(self):
        # Stop the generator thread
        if self.generator:
            self.generator.stop()
            self.generator.join()
            self.generator = None
        # Close the PeerConnection
        if self.pc:
            await self.pc.close()
            self.pc = None

    def _prefer_h264(self, sdp: str) -> str:
        """
        If the SDP contains H.264, reorder the m=video payloads so that H.264’s payload number is first.
        Otherwise returns the SDP unchanged.
        """
        lines = sdp.split("\r\n")
        result = []
        payload_to_codec = {}

        # Build a map of payload number -> codec name
        for line in lines:
            if line.startswith("a=rtpmap:"):
                parts = line[9:].split(" ")
                pt = parts[0]
                codec = parts[1].split("/")[0]
                payload_to_codec[pt] = codec.lower()

        # Find H.264 payload number(s)
        h264_pts = [pt for pt, codec in payload_to_codec.items() if codec == "h264"]
        chosen_pt = h264_pts[0] if h264_pts else None

        # Rebuild SDP, rewriting the m=video line if H.264 is present
        for line in lines:
            if line.startswith("m=video"):
                parts = line.split(" ")
                prefix = parts[:3]   # ["m=video", "<port>", "<proto>"]
                pts = parts[3:]      # list of payload numbers
                if chosen_pt and chosen_pt in pts:
                    # Move H.264 payload to front
                    reordered = [chosen_pt] + [p for p in pts if p != chosen_pt]
                    result.append(" ".join(prefix + reordered))
                else:
                    result.append(line)
            else:
                result.append(line)

        return "\r\n".join(result)

# -----------------------------
# WebTransportProtocol
# -----------------------------
class WebTransportProtocol(QuicConnectionProtocol):
    """
    QUIC protocol that handles HTTP/3 → WebTransport handshake.
    On CONNECT /webtransport, it creates a SessionHandler to handle streams/datagrams.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._http: H3Connection = None
        self._handler: SessionHandler = None

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, ProtocolNegotiated):
            # Once ALPN is negotiated, initialize H3Connection with WebTransport enabled
            self._http = H3Connection(self._quic, enable_webtransport=True)

        if self._http is not None:
            for h3_event in self._http.handle_event(event):
                self._h3_event_received(h3_event)

    def _h3_event_received(self, event) -> None:
        # Handle incoming HEADERS (for CONNECT /webtransport)
        if isinstance(event, HeadersReceived):
            headers = {name: value for name, value in event.headers}
            method = headers.get(b":method")
            protocol = headers.get(b":protocol")
            path = headers.get(b":path")
            if method == b"CONNECT" and protocol == b"webtransport" and path == b"/webtransport":
                # Handshake WebTransport
                self._handler = SessionHandler(event.stream_id, self._http, asyncio.get_event_loop())
                self._send_response(event.stream_id, 200)
            else:
                # Only /webtransport is supported
                self._send_response(event.stream_id, 404, end_stream=True)
            return

        # If we have a handler, forward relevant events
        if self._handler:
            # Pass through DATAGRAM and WebTransport streams
            if isinstance(event, (DatagramReceived, WebTransportStreamDataReceived, StreamReset)):
                self._handler.h3_event_received(event)

    def _send_response(self, stream_id: int, status_code: int, end_stream: bool = False) -> None:
        headers = [(b":status", str(status_code).encode())]
        if status_code == 200:
            headers.append((b"sec-webtransport-http3-draft", b"draft02"))
        self._http.send_headers(stream_id=stream_id, headers=headers, end_stream=end_stream)


# -----------------------------
# Main: QUIC Server Setup
# -----------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Bouncing‐Ball WebTransport + WebRTC (aiortc) Server"
    )
    parser.add_argument("certificate", help="TLS certificate file (PEM)")
    parser.add_argument("key", help="TLS private key file (PEM)")
    parser.add_argument(
        "--bind-address", default="::1", help="IP address to bind (default ::1)"
    )
    parser.add_argument(
        "--bind-port", type=int, default=4433, help="Port to bind (default 4433)"
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(level=logging.INFO)

    # QUIC configuration: HTTP/3 with WebTransport enabled
    configuration = QuicConfiguration(
        alpn_protocols=H3_ALPN, is_client=False, max_datagram_frame_size=65536
    )
    configuration.load_cert_chain(args.certificate, args.key)

    loop = asyncio.get_event_loop()

    # Graceful shutdown: on SIGINT/SIGTERM, stop loop
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, loop.stop)

    # Start QUIC server
    server_coro = serve(
        args.bind_address,
        args.bind_port,
        configuration=configuration,
        create_protocol=WebTransportProtocol,
    )
    loop.run_until_complete(server_coro)
    logger.info(f"Listening on https://{args.bind_address}:{args.bind_port}/webtransport")
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()


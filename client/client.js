// client.js by Rudrashis Gorai

;(async () => {
  // 1. Grab DOM elements
  const remoteVideo = document.getElementById("remoteVideo");
  const errorDisplay = document.getElementById("errorDisplay");
  const hiddenCanvas = document.getElementById("hiddenCanvas");
  const ctx = hiddenCanvas.getContext("2d");

  // 2. Create WebTransport connection (HTTP/3 + WebTransport)
  let transport;
  try {
    transport = new WebTransport("https://localhost:4433/webtransport");
    await transport.ready; // wait until QUIC handshake completes
    console.log("WebTransport ready; creating RTCPeerConnection...");
  } catch (err) {
    console.error("Failed to open WebTransport:", err);
    return;
  }

  // 3. Create RTCPeerConnection (no ICE servers required)
  const pc = new RTCPeerConnection({ iceServers: [] });

  // 4. Force H.264 as the only video codec
  {
    const transceiver = pc.addTransceiver("video", { direction: "sendrecv" });
    const capabilities = RTCRtpSender.getCapabilities("video");
    const h264Codecs = capabilities.codecs.filter(c => c.mimeType === "video/H264");
    if (h264Codecs.length > 0) {
      transceiver.setCodecPreferences(h264Codecs);
    } else {
      console.warn("H.264 codec not available in this browser!");
    }
    // Remove dummy sender immediately
    await transceiver.sender.replaceTrack(null);
  }

  // 5. Handle incoming video track
  pc.ontrack = event => {
    const [stream] = event.streams;
    remoteVideo.muted = true;  // Allow autoplay of the stream
    console.log("[DEBUG] Received remote stream:", stream);
    remoteVideo.srcObject = stream;

    // Log when the first frame is decoded
    remoteVideo.addEventListener("loadeddata", () => {
      console.log(
        "[DEBUG] <video> loadeddata, readyState =", remoteVideo.readyState
      );
      console.log(
        "[DEBUG] <video> size =", remoteVideo.videoWidth, "x", remoteVideo.videoHeight
      );
    });
  };

  // 6. Log connection state changes
  pc.onconnectionstatechange = () => {
    console.log("PeerConnection state:", pc.connectionState);
  };

  // 7. Create SDP offer and set local description
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  console.log("Created SDP offer, localDescription set.");

  // 8. Send the SDP offer over WebTransport (unidirectional stream)
  {
    const sdpOffer = { type: "offer", sdp: pc.localDescription.sdp };
    const jsonBytes = new TextEncoder().encode(JSON.stringify(sdpOffer));
    const sendStream = await transport.createUnidirectionalStream();
    const writer = sendStream.getWriter();
    await writer.write(jsonBytes);
    await writer.close();
    console.log("Sent SDP offer over WebTransport stream.");
  }

  // 9. Read incoming unidirectional streams (SDP answer)
  const uniReader = transport.incomingUnidirectionalStreams.getReader();
  while (true) {
    const { value: uniStream, done } = await uniReader.read();
    if (done) break;
    const ds = uniStream.getReader();
    let chunks = [];
    while (true) {
      const { value: chunk, done: chunkDone } = await ds.read();
      if (chunkDone) break;
      chunks.push(chunk);
    }
    let totalLength = chunks.reduce((sum, c) => sum + c.byteLength, 0);
    let raw = new Uint8Array(totalLength);
    let offset = 0;
    for (const c of chunks) {
      raw.set(c, offset);
      offset += c.byteLength;
    }
    try {
      const msg = JSON.parse(new TextDecoder().decode(raw));
      if (msg.type === "answer") {
        console.log("Received SDP answer:", msg.sdp);
        await pc.setRemoteDescription(
          new RTCSessionDescription({ type: "answer", sdp: msg.sdp })
        );
        console.log("Set remoteDescription with answer.");
        break;

      }
    } catch (e) {
      console.error("Failed to parse SDP answer:", e);
    }
  }

  // 10. Size the hidden canvas once metadata is available
  remoteVideo.addEventListener("loadedmetadata", () => {
    hiddenCanvas.width = remoteVideo.videoWidth;
    hiddenCanvas.height = remoteVideo.videoHeight;
    console.log(
      "[DEBUG] Hidden canvas sized to", hiddenCanvas.width, "x", hiddenCanvas.height
    );
  });

  // 11. Function to detect the green ball’s center
  function detectBall() {
    const w = remoteVideo.videoWidth;
    const h = remoteVideo.videoHeight;
    if (w === 0 || h === 0) return null;

    ctx.drawImage(remoteVideo, 0, 0, w, h);
    const imgData = ctx.getImageData(0, 0, w, h);
    const data = imgData.data;

    let sumX = 0, sumY = 0, count = 0;
    for (let y = 0; y < h; y += 4) {
      for (let x = 0; x < w; x += 4) {
        const idx = (y * w + x) * 4;
        const r = data[idx], g = data[idx + 1], b = data[idx + 2];
        if (g > 200 && r < 50 && b < 50) {
          sumX += x;
          sumY += y;
          count++;
        }
      }
    }
    if (count === 0) return null;
    return { x: sumX / count, y: sumY / count };
  }
  window.detectBall = detectBall; // Optional: expose for manual debugging

    // 12. Instead of a fixed‐interval setInterval, use requestAnimationFrame
    function sendCoordsLoop() {
      // Only attempt detection if a frame is available
      if (remoteVideo.readyState >= 2) {
        const coords = detectBall();
        if (coords) {
          const msg = { type: "coords", x: coords.x, y: coords.y };
          const bytes = new TextEncoder().encode(JSON.stringify(msg));
          const writer = transport.datagrams.writable.getWriter();
          writer.write(bytes);
          writer.releaseLock();
          // console.log("[DEBUG] Sent coords:", coords);
        }
      }
      // Schedule next run at the next repaint
      requestAnimationFrame(sendCoordsLoop);
    }
  
    // Kick off the first iteration once playback has started
    remoteVideo.addEventListener("playing", () => {
      console.log("[DEBUG] Video is playing; starting coords loop.");
      requestAnimationFrame(sendCoordsLoop);
    });
  
    // 13. Listen for incoming datagrams (errors) from the server
    (async () => {
      const datagramReader = transport.datagrams.readable.getReader();
      while (true) {
        try {
          const { value: datagramBytes, done } = await datagramReader.read();
          if (done) {
            console.log("[DEBUG] Datagram reader closed");
            break;
          }
          const msg = JSON.parse(new TextDecoder().decode(datagramBytes));
          // console.log("[DEBUG] Received datagram from server:", msg);
          if (msg.type === "error") {
            const e = parseFloat(msg.e);
            errorDisplay.textContent = `Error: ${e.toFixed(2)} px`;
          }
        } catch (err) {
          console.error("[DEBUG] Datagram reader error:", err);
          break;
        }
      }
    })();
  

  // 14. Optional: Log if the WebTransport session closes or errors
  transport.closed
    .then(() => {
      console.log("WebTransport session closed");
    })
    .catch(err => {
      console.error("WebTransport session error:", err);
    });
})();

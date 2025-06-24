import asyncio
import threading
import time

import cv2
import numpy as np
import pytest
from av import VideoFrame
import os
import sys

THIS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from server.server import BouncingBallGenerator, BouncingBallMediaTrack

def test_generator_emits_frame_and_position_changes():
    """
    Start BouncingBallGenerator at a low fps (e.g. 5). Wait up to 0.5s for the first frame to appear.
    Then wait another ~1/fps seconds and ensure that get_position() has changed.
    Finally, stop the generator.
    """
    fps = 5
    gen = BouncingBallGenerator(width=16, height=16, fps=fps, save_frames=False)
    gen.start()

    # (1) Wait up to 0.5s for a non-None frame
    first_frame = None
    t_start = time.time()
    while first_frame is None and (time.time() - t_start) < 0.5:
        first_frame = gen.get_frame()
        time.sleep(0.01)
    assert first_frame is not None, "Generator did not produce any frame within 0.5s"

    # (2) Record initial position, wait ~1/fps, then check that position has changed
    x0, y0 = gen.get_position()
    time.sleep(1.0 / fps + 0.05)  # wait a bit longer than one frame interval
    x1, y1 = gen.get_position()
    # Position should not be exactly the same (ball must have moved)
    assert (x0, y0) != (x1, y1), f"Expected position to change (was {(x0, y0)}), but remains unchanged"

    # (3) Cleanup
    gen.stop()
    gen.join(timeout=0.5)
    assert not gen.is_alive(), "Generator thread did not stop cleanly"


def test_media_track_recv_returns_video_frame():
    """
    Create a BouncingBallGenerator that immediately produces one black frame
    (we manually set its _frame). Wrap it in BouncingBallMediaTrack and call recv() once.
    The returned object should be an av.VideoFrame with correct width/height.
    """
    # (1) Create a dummy generator with a single frame already available.
    gen = BouncingBallGenerator(width=12, height=8, fps=1, save_frames=False)
    # Instead of starting its run loop, manually inject one frame:
    dummy_arr = np.zeros((gen.height, gen.width, 3), dtype=np.uint8)
    with gen.lock:
        gen._frame = dummy_arr.copy()
        gen._pos = (gen.x, gen.y)
    # We do not call gen.start(), so no thread is running.

    # (2) Wrap it into the media track
    track_wrapper = BouncingBallMediaTrack(gen)
    track = track_wrapper.track

    # The first call to next_timestamp() requires an event loop; we can run it via asyncio
    # But aiortc's VideoStreamTrack.recv() can be tested by creating a simple asyncio loop.
    import asyncio

    async def _get_frame():
        frame: VideoFrame = await track.recv()
        return frame

    # Create and run a new event loop for this async call
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    frame: VideoFrame = loop.run_until_complete(_get_frame())
    loop.close()

    # (3) Assertions on the returned VideoFrame
    assert isinstance(frame, VideoFrame), "recv() did not return an av.VideoFrame"
    # The frame's dimensions (in PixelFormat) for a bgr24 frame should match the generator dims.
    # Note: VideoFrame.width & height reflect the display size, but if untested, at least ensure
    # that the frame planes exist. We can convert to ndarray:
    arr = frame.to_ndarray(format="bgr24")
    assert arr.shape[0] == gen.height  # height
    assert arr.shape[1] == gen.width   # width
    # Colors should match a black image
    assert np.all(arr == 0), "Injected frame did not come through as black"


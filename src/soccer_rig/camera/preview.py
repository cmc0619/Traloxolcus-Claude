"""
Live preview server for camera feed.

Provides MJPEG streaming for the Web UI.
"""

import io
import time
import threading
import logging
from typing import Optional, Generator

logger = logging.getLogger(__name__)


class PreviewServer:
    """
    Handles live preview streaming for the camera.

    Provides:
    - MJPEG streaming for web UI
    - Configurable frame rate
    - Low-latency preview during framing
    """

    def __init__(self, recorder, target_fps: int = 10):
        """
        Initialize preview server.

        Args:
            recorder: CameraRecorder instance
            target_fps: Target frames per second for preview
        """
        self.recorder = recorder
        self.target_fps = target_fps
        self._running = False
        self._frame: Optional[bytes] = None
        self._frame_lock = threading.Lock()
        self._update_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start preview capture thread."""
        if self._running:
            return

        self._running = True
        self._update_thread = threading.Thread(
            target=self._capture_loop,
            daemon=True
        )
        self._update_thread.start()
        logger.info("Preview server started")

    def stop(self) -> None:
        """Stop preview capture thread."""
        self._running = False
        if self._update_thread:
            self._update_thread.join(timeout=2.0)
        logger.info("Preview server stopped")

    def _capture_loop(self) -> None:
        """Background thread to capture preview frames."""
        frame_interval = 1.0 / self.target_fps

        while self._running:
            start_time = time.time()

            try:
                frame = self.recorder.get_preview_frame()
                if frame:
                    with self._frame_lock:
                        self._frame = frame
            except Exception as e:
                logger.error(f"Preview capture error: {e}")

            # Maintain target frame rate
            elapsed = time.time() - start_time
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def get_frame(self) -> Optional[bytes]:
        """Get the latest preview frame."""
        with self._frame_lock:
            return self._frame

    def generate_mjpeg(self) -> Generator[bytes, None, None]:
        """
        Generate MJPEG stream for HTTP response.

        Yields:
            MJPEG frame data with boundaries
        """
        boundary = b"--frame\r\n"
        content_type = b"Content-Type: image/jpeg\r\n\r\n"

        while self._running:
            frame = self.get_frame()

            if frame:
                yield boundary
                yield content_type
                yield frame
                yield b"\r\n"

            time.sleep(1.0 / self.target_fps)

    def get_single_frame_response(self) -> tuple:
        """
        Get a single frame as HTTP response data.

        Returns:
            Tuple of (frame_bytes, content_type)
        """
        frame = self.get_frame()
        if frame:
            return frame, "image/jpeg"

        # Return placeholder if no frame available
        return self._generate_placeholder(), "image/jpeg"

    def _generate_placeholder(self) -> bytes:
        """Generate a placeholder image when no frame available."""
        try:
            from PIL import Image, ImageDraw, ImageFont

            # Create a simple placeholder
            img = Image.new("RGB", (640, 480), color=(40, 40, 40))
            draw = ImageDraw.Draw(img)

            # Add text
            text = "No Preview Available"
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

            # Center the text
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = (640 - text_width) // 2
            y = (480 - text_height) // 2
            draw.text((x, y), text, fill=(200, 200, 200), font=font)

            # Convert to JPEG
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=80)
            return buffer.getvalue()

        except ImportError:
            # Return minimal valid JPEG if PIL not available
            return self._minimal_jpeg()

    def _minimal_jpeg(self) -> bytes:
        """Return a minimal valid JPEG placeholder."""
        # Minimal 1x1 gray JPEG
        return bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46,
            0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
            0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
            0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08,
            0x07, 0x07, 0x07, 0x09, 0x09, 0x08, 0x0A, 0x0C,
            0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
            0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D,
            0x1A, 0x1C, 0x1C, 0x20, 0x24, 0x2E, 0x27, 0x20,
            0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
            0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27,
            0x39, 0x3D, 0x38, 0x32, 0x3C, 0x2E, 0x33, 0x34,
            0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
            0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4,
            0x00, 0x1F, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01,
            0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04,
            0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0xFF,
            0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
            0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04,
            0x00, 0x00, 0x01, 0x7D, 0x01, 0x02, 0x03, 0x00,
            0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
            0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32,
            0x81, 0x91, 0xA1, 0x08, 0x23, 0x42, 0xB1, 0xC1,
            0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
            0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A,
            0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x34, 0x35,
            0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
            0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55,
            0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00,
            0x3F, 0x00, 0x7F, 0xFF, 0xD9
        ])

"""
Soccer field framing detection module.

Uses OpenCV to detect:
- Green grass coverage (field presence)
- White line detection (field markings)
- Overall framing quality score

Provides audio feedback when field is properly framed.
"""

from __future__ import annotations  # Enable string annotations for type hints

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING
from enum import Enum

# Type hints for numpy arrays when cv2 is not available
if TYPE_CHECKING:
    import numpy as np

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None  # type: ignore
    np = None  # type: ignore
    CV2_AVAILABLE = False

logger = logging.getLogger(__name__)


class FramingStatus(Enum):
    """Framing quality status."""
    UNKNOWN = "unknown"
    NO_FIELD = "no_field"
    PARTIAL = "partial"
    GOOD = "good"
    EXCELLENT = "excellent"


@dataclass
class FramingResult:
    """Result of framing analysis."""
    status: FramingStatus
    score: float  # 0.0 to 1.0
    grass_coverage: float  # Percentage of frame that is grass
    lines_detected: int  # Number of field lines detected
    has_center_line: bool
    has_penalty_area: bool
    has_sideline: bool
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "score": round(self.score, 2),
            "grass_coverage": round(self.grass_coverage, 2),
            "lines_detected": self.lines_detected,
            "has_center_line": self.has_center_line,
            "has_penalty_area": self.has_penalty_area,
            "has_sideline": self.has_sideline,
            "message": self.message,
        }


class FramingDetector:
    """
    Detects soccer field framing quality from camera frames.

    Uses color-based grass detection and Hough line transform
    to identify field markings.
    """

    # HSV ranges for grass detection (green)
    GRASS_HSV_LOWER = (35, 40, 40)
    GRASS_HSV_UPPER = (85, 255, 255)

    # Thresholds
    MIN_GRASS_COVERAGE = 0.40  # 40% of frame should be grass
    GOOD_GRASS_COVERAGE = 0.60  # 60% for good framing
    MIN_LINES_FOR_GOOD = 3  # At least 3 lines visible

    def __init__(self, config=None):
        """
        Initialize framing detector.

        Args:
            config: Optional configuration object
        """
        self.config = config
        self._last_result: Optional[FramingResult] = None
        self._last_analysis_time: float = 0
        self._analysis_interval = 0.5  # Analyze every 500ms max
        self._lock = threading.Lock()

        if not CV2_AVAILABLE:
            logger.warning("OpenCV not available - framing detection disabled")

    def analyze_frame(self, frame: Any) -> FramingResult:
        """
        Analyze a camera frame for field framing quality.

        Args:
            frame: numpy array (BGR image) or picamera2 frame

        Returns:
            FramingResult with analysis details
        """
        if not CV2_AVAILABLE:
            return FramingResult(
                status=FramingStatus.UNKNOWN,
                score=0.0,
                grass_coverage=0.0,
                lines_detected=0,
                has_center_line=False,
                has_penalty_area=False,
                has_sideline=False,
                message="OpenCV not available"
            )

        # Rate limit analysis
        now = time.time()
        if now - self._last_analysis_time < self._analysis_interval:
            if self._last_result:
                return self._last_result

        self._last_analysis_time = now

        try:
            # Convert frame if needed
            if hasattr(frame, 'array'):
                # picamera2 frame
                img = frame.array
            else:
                img = frame

            # Resize for faster processing (720p is enough for detection)
            height, width = img.shape[:2]
            scale = min(1.0, 1280 / width)
            if scale < 1.0:
                img = cv2.resize(img, None, fx=scale, fy=scale)

            # Analyze grass coverage
            grass_coverage, grass_mask = self._detect_grass(img)

            # Detect field lines
            lines, line_info = self._detect_lines(img, grass_mask)

            # Calculate overall score and status
            result = self._calculate_framing_score(
                grass_coverage, lines, line_info
            )

            with self._lock:
                self._last_result = result

            return result

        except Exception as e:
            logger.error(f"Framing analysis error: {e}")
            return FramingResult(
                status=FramingStatus.UNKNOWN,
                score=0.0,
                grass_coverage=0.0,
                lines_detected=0,
                has_center_line=False,
                has_penalty_area=False,
                has_sideline=False,
                message=f"Analysis error: {str(e)}"
            )

    def _detect_grass(self, img: np.ndarray) -> Tuple[float, np.ndarray]:
        """
        Detect grass (green areas) in the image.

        Returns:
            Tuple of (coverage_percentage, binary_mask)
        """
        # Convert to HSV
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # Create mask for green grass
        mask = cv2.inRange(hsv, self.GRASS_HSV_LOWER, self.GRASS_HSV_UPPER)

        # Clean up mask with morphology
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        # Calculate coverage
        total_pixels = mask.shape[0] * mask.shape[1]
        grass_pixels = cv2.countNonZero(mask)
        coverage = grass_pixels / total_pixels

        return coverage, mask

    def _detect_lines(self, img: np.ndarray, grass_mask: np.ndarray) -> Tuple[list, Dict]:
        """
        Detect white field lines in the image.

        Returns:
            Tuple of (lines_list, line_info_dict)
        """
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Apply grass mask to focus on field area
        gray_masked = cv2.bitwise_and(gray, gray, mask=grass_mask)

        # Detect white areas (field lines are white)
        _, white_mask = cv2.threshold(gray_masked, 200, 255, cv2.THRESH_BINARY)

        # Edge detection
        edges = cv2.Canny(white_mask, 50, 150, apertureSize=3)

        # Dilate edges slightly to connect broken lines
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)

        # Hough Line Transform
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=50,
            minLineLength=50,
            maxLineGap=20
        )

        if lines is None:
            lines = []
        else:
            lines = lines.tolist()

        # Analyze line orientations
        line_info = self._analyze_lines(lines, img.shape)

        return lines, line_info

    def _analyze_lines(self, lines: list, img_shape: tuple) -> Dict:
        """
        Analyze detected lines for field features.

        Returns:
            Dict with line analysis info
        """
        info = {
            "horizontal_lines": 0,
            "vertical_lines": 0,
            "has_center_line": False,
            "has_sideline": False,
            "has_penalty_area": False,
        }

        if not lines:
            return info

        height, width = img_shape[:2]
        center_x = width // 2
        center_y = height // 2

        for line in lines:
            x1, y1, x2, y2 = line[0]

            # Calculate angle
            dx = x2 - x1
            dy = y2 - y1

            if dx == 0:
                angle = 90
            else:
                angle = abs(np.degrees(np.arctan(dy / dx)))

            # Classify line orientation
            if angle < 30:
                # Horizontal line
                info["horizontal_lines"] += 1

                # Check if it's near the middle (potential center line or sideline)
                line_y = (y1 + y2) // 2
                if abs(line_y - center_y) < height * 0.2:
                    info["has_sideline"] = True

            elif angle > 60:
                # Vertical line
                info["vertical_lines"] += 1

                # Check if it's near center (potential center line)
                line_x = (x1 + x2) // 2
                if abs(line_x - center_x) < width * 0.15:
                    info["has_center_line"] = True

                # Check for penalty area lines (at edges)
                if line_x < width * 0.25 or line_x > width * 0.75:
                    info["has_penalty_area"] = True

        return info

    def _calculate_framing_score(
        self,
        grass_coverage: float,
        lines: list,
        line_info: Dict
    ) -> FramingResult:
        """
        Calculate overall framing score and status.
        """
        num_lines = len(lines)

        # Base score from grass coverage (0-50 points)
        grass_score = min(grass_coverage / self.GOOD_GRASS_COVERAGE, 1.0) * 50

        # Line score (0-30 points)
        line_score = min(num_lines / 10, 1.0) * 30

        # Feature bonus (0-20 points)
        feature_score = 0
        if line_info["has_center_line"]:
            feature_score += 8
        if line_info["has_sideline"]:
            feature_score += 6
        if line_info["has_penalty_area"]:
            feature_score += 6

        # Total score (0-100, convert to 0-1)
        total_score = (grass_score + line_score + feature_score) / 100

        # Determine status
        if grass_coverage < 0.20:
            status = FramingStatus.NO_FIELD
            message = "No soccer field detected - point camera at the field"
        elif grass_coverage < self.MIN_GRASS_COVERAGE:
            status = FramingStatus.PARTIAL
            message = f"Partial field view ({int(grass_coverage*100)}% grass) - adjust camera angle"
        elif num_lines < 2:
            status = FramingStatus.PARTIAL
            message = "Field visible but no lines detected - check focus and lighting"
        elif total_score < 0.5:
            status = FramingStatus.PARTIAL
            message = "Partial framing - adjust to capture more field lines"
        elif total_score < 0.75:
            status = FramingStatus.GOOD
            message = "Good framing - field and lines visible"
        else:
            status = FramingStatus.EXCELLENT
            message = "Excellent framing - field well captured"

        return FramingResult(
            status=status,
            score=total_score,
            grass_coverage=grass_coverage,
            lines_detected=num_lines,
            has_center_line=line_info["has_center_line"],
            has_penalty_area=line_info["has_penalty_area"],
            has_sideline=line_info["has_sideline"],
            message=message,
        )

    def get_last_result(self) -> Optional[FramingResult]:
        """Get the most recent framing result."""
        with self._lock:
            return self._last_result

    def get_status(self) -> Dict[str, Any]:
        """Get current framing status as dict."""
        result = self.get_last_result()
        if result:
            return result.to_dict()
        return {
            "status": "unknown",
            "score": 0,
            "message": "No analysis performed yet"
        }


class FramingAssistant:
    """
    Provides real-time framing assistance with audio feedback.

    Monitors camera frames and provides audio cues when:
    - Field comes into view
    - Framing quality changes
    - Field is properly framed (confirmation beep)
    """

    def __init__(self, detector: FramingDetector, audio_feedback=None):
        """
        Initialize framing assistant.

        Args:
            detector: FramingDetector instance
            audio_feedback: AudioFeedback instance for beeps
        """
        self.detector = detector
        self.audio = audio_feedback

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frame_source = None

        self._last_status = FramingStatus.UNKNOWN
        self._good_frame_time: Optional[float] = None
        self._confirmed = False

        # Timing for audio feedback
        self._last_beep_time = 0
        self._beep_cooldown = 2.0  # Seconds between status beeps

    def start(self, frame_source) -> None:
        """
        Start framing assistance.

        Args:
            frame_source: Callable that returns current camera frame
        """
        if self._running:
            return

        self._frame_source = frame_source
        self._running = True
        self._confirmed = False

        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

        logger.info("Framing assistant started")

    def stop(self) -> None:
        """Stop framing assistance."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        logger.info("Framing assistant stopped")

    def reset(self) -> None:
        """Reset confirmation state (for repositioning)."""
        self._confirmed = False
        self._good_frame_time = None
        self._last_status = FramingStatus.UNKNOWN

    def is_confirmed(self) -> bool:
        """Check if good framing has been confirmed."""
        return self._confirmed

    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                if self._frame_source:
                    frame = self._frame_source()
                    if frame is not None:
                        result = self.detector.analyze_frame(frame)
                        self._handle_result(result)

                time.sleep(0.5)  # Check twice per second

            except Exception as e:
                logger.error(f"Framing monitor error: {e}")
                time.sleep(1)

    def _handle_result(self, result: FramingResult) -> None:
        """Handle framing analysis result with audio feedback."""
        now = time.time()
        status = result.status

        # Status changed
        if status != self._last_status:
            self._on_status_change(self._last_status, status, result)
            self._last_status = status

        # Track time at good/excellent framing
        if status in (FramingStatus.GOOD, FramingStatus.EXCELLENT):
            if self._good_frame_time is None:
                self._good_frame_time = now

            # Confirm after 2 seconds of good framing
            if not self._confirmed and (now - self._good_frame_time) >= 2.0:
                self._confirm_framing()
        else:
            self._good_frame_time = None

    def _on_status_change(
        self,
        old_status: FramingStatus,
        new_status: FramingStatus,
        result: FramingResult
    ) -> None:
        """Handle status change with appropriate feedback."""
        now = time.time()

        # Cooldown check
        if now - self._last_beep_time < self._beep_cooldown:
            return

        if not self.audio:
            return

        # No field -> field detected
        if old_status == FramingStatus.NO_FIELD and new_status != FramingStatus.NO_FIELD:
            self.audio.beep_custom(frequency=600, duration=0.1, count=1)
            self._last_beep_time = now
            logger.info("Field detected")

        # Became good/excellent
        elif new_status in (FramingStatus.GOOD, FramingStatus.EXCELLENT) and \
             old_status not in (FramingStatus.GOOD, FramingStatus.EXCELLENT):
            self.audio.beep_custom(frequency=800, duration=0.1, count=2)
            self._last_beep_time = now
            logger.info(f"Good framing: {result.message}")

        # Lost good framing
        elif new_status not in (FramingStatus.GOOD, FramingStatus.EXCELLENT) and \
             old_status in (FramingStatus.GOOD, FramingStatus.EXCELLENT):
            self.audio.beep_custom(frequency=400, duration=0.2, count=1)
            self._last_beep_time = now
            self._confirmed = False
            logger.info(f"Framing lost: {result.message}")

    def _confirm_framing(self) -> None:
        """Confirm good framing with distinctive beep."""
        self._confirmed = True

        if self.audio:
            # Distinctive confirmation: rising tone
            self.audio.beep_custom(frequency=600, duration=0.1, count=1)
            time.sleep(0.15)
            self.audio.beep_custom(frequency=800, duration=0.1, count=1)
            time.sleep(0.15)
            self.audio.beep_custom(frequency=1000, duration=0.2, count=1)

        logger.info("Framing confirmed - camera is properly positioned")

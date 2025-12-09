"""
GPU-accelerated video stitcher.

Combines 3 camera views (left, center, right) into a single
seamless panorama video with smooth blending.

Uses:
- FFmpeg with NVENC for GPU-accelerated encoding
- OpenCV for frame blending
- CUDA for image processing (when available)
"""

import logging
import subprocess
import threading
import queue
import shutil
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from enum import Enum

logger = logging.getLogger(__name__)

# Try to import GPU-accelerated libraries
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("OpenCV not available")

try:
    import cupy as cp
    CUPY_AVAILABLE = True
except ImportError:
    CUPY_AVAILABLE = False


class StitchStatus(Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    STITCHING = "stitching"
    ENCODING = "encoding"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StitchJob:
    """Represents a video stitching job."""
    job_id: str
    session_id: str
    input_videos: Dict[str, Path]  # {"CAM_L": path, "CAM_C": path, "CAM_R": path}
    output_path: Path
    status: StitchStatus = StitchStatus.PENDING
    progress: float = 0.0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class CameraCalibration:
    """
    Camera calibration data for stitching.

    Stores homography matrices and blend masks for
    seamless panorama creation.
    """

    def __init__(self, calibration_file: Optional[str] = None):
        self.homography_left: Optional[np.ndarray] = None
        self.homography_right: Optional[np.ndarray] = None
        self.blend_mask_left: Optional[np.ndarray] = None
        self.blend_mask_right: Optional[np.ndarray] = None
        self.output_size: Tuple[int, int] = (5760, 1080)

        if calibration_file and Path(calibration_file).exists():
            self.load(calibration_file)
        else:
            self._create_default_calibration()

    def _create_default_calibration(self):
        """
        Create default calibration assuming cameras are roughly aligned.

        In production, run actual calibration with checkerboard pattern.
        """
        # Default: Simple horizontal stacking with overlap
        # Assumes 1920x1080 per camera, 100px overlap on each side
        # Output: 5760x1080 (1920 + 1920 + 1920 - 2*100 overlap... simplified to just stack)

        w, h = 1920, 1080
        overlap = 100

        # Left camera: shift to position 0
        self.homography_left = np.array([
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1]
        ], dtype=np.float32)

        # Right camera: shift to position 2*w - overlap
        self.homography_right = np.array([
            [1, 0, 2 * w - 2 * overlap],
            [0, 1, 0],
            [0, 0, 1]
        ], dtype=np.float32)

        # Center camera stays in the middle
        # (handled separately in stitching)

        # Create blend masks for smooth transitions
        self.blend_mask_left = self._create_blend_mask(w, h, "right")
        self.blend_mask_right = self._create_blend_mask(w, h, "left")

        self.output_size = (3 * w - 2 * overlap, h)

    def _create_blend_mask(self, width: int, height: int, fade_side: str) -> np.ndarray:
        """Create a gradient mask for blending."""
        mask = np.ones((height, width), dtype=np.float32)
        blend_width = 100

        if fade_side == "right":
            # Fade out on the right side
            for i in range(blend_width):
                mask[:, width - blend_width + i] = 1.0 - (i / blend_width)
        elif fade_side == "left":
            # Fade out on the left side
            for i in range(blend_width):
                mask[:, i] = i / blend_width

        return mask

    def load(self, path: str):
        """Load calibration from file."""
        with open(path) as f:
            data = json.load(f)

        self.homography_left = np.array(data["homography_left"], dtype=np.float32)
        self.homography_right = np.array(data["homography_right"], dtype=np.float32)
        self.output_size = tuple(data["output_size"])
        # Recreate blend masks based on loaded data
        self._create_default_calibration()

    def save(self, path: str):
        """Save calibration to file."""
        data = {
            "homography_left": self.homography_left.tolist(),
            "homography_right": self.homography_right.tolist(),
            "output_size": list(self.output_size),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


class VideoStitcher:
    """
    GPU-accelerated panorama video stitcher.

    Pipeline:
    1. Analyze input videos (duration, fps, codec)
    2. Frame-by-frame stitching with blending
    3. GPU-accelerated encoding to output
    """

    def __init__(self, config):
        self.config = config
        self.calibration = CameraCalibration(config.stitcher.calibration_file)

        self.job_queue: queue.Queue = queue.Queue()
        self.current_job: Optional[StitchJob] = None
        self.jobs: Dict[str, StitchJob] = {}

        self._worker_thread: Optional[threading.Thread] = None
        self._running = False

        # Check GPU availability
        self.gpu_available = self._check_gpu()
        if self.gpu_available:
            logger.info("GPU encoding available (NVENC)")
        else:
            logger.warning("GPU not available, using CPU encoding")

    def _check_gpu(self) -> bool:
        """Check if NVENC GPU encoding is available."""
        if not self.config.stitcher.use_gpu:
            return False

        try:
            result = subprocess.run(
                ["ffmpeg", "-encoders"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return "h264_nvenc" in result.stdout
        except Exception:
            return False

    def start(self):
        """Start the stitching worker thread."""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("Video stitcher started")

    def stop(self):
        """Stop the stitching worker."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        logger.info("Video stitcher stopped")

    def queue_stitch(
        self,
        session_id: str,
        input_videos: Dict[str, Path],
        output_path: Path
    ) -> str:
        """
        Queue a new stitching job.

        Args:
            session_id: Session identifier
            input_videos: Dict mapping camera IDs to video paths
            output_path: Where to write the panorama

        Returns:
            Job ID
        """
        job_id = f"stitch_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        job = StitchJob(
            job_id=job_id,
            session_id=session_id,
            input_videos=input_videos,
            output_path=output_path,
        )

        self.jobs[job_id] = job
        self.job_queue.put(job)
        logger.info(f"Queued stitch job: {job_id}")

        return job_id

    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get status of a stitch job."""
        job = self.jobs.get(job_id)
        if not job:
            return None

        return {
            "job_id": job.job_id,
            "session_id": job.session_id,
            "status": job.status.value,
            "progress": job.progress,
            "error": job.error,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }

    def _worker_loop(self):
        """Main worker loop for processing stitch jobs."""
        while self._running:
            try:
                job = self.job_queue.get(timeout=1)
                self._process_job(job)
            except queue.Empty:
                continue
            except Exception as e:
                logger.exception(f"Worker error: {e}")

    def _process_job(self, job: StitchJob):
        """Process a single stitch job."""
        job.started_at = datetime.now()
        job.status = StitchStatus.ANALYZING
        self.current_job = job

        logger.info(f"Processing stitch job: {job.job_id}")

        try:
            # Validate inputs
            for cam_id, path in job.input_videos.items():
                if not Path(path).exists():
                    raise FileNotFoundError(f"Missing video: {cam_id} -> {path}")

            # Get video info
            video_info = self._analyze_videos(job.input_videos)
            job.metadata["video_info"] = video_info

            # Perform stitching
            job.status = StitchStatus.STITCHING
            self._stitch_videos(job, video_info)

            job.status = StitchStatus.COMPLETED
            job.progress = 100.0
            job.completed_at = datetime.now()

            duration = (job.completed_at - job.started_at).total_seconds()
            logger.info(f"Stitch job completed: {job.job_id} in {duration:.1f}s")

        except Exception as e:
            job.status = StitchStatus.FAILED
            job.error = str(e)
            logger.error(f"Stitch job failed: {job.job_id} - {e}")

        finally:
            self.current_job = None

    def _analyze_videos(self, videos: Dict[str, Path]) -> Dict[str, Any]:
        """Analyze input videos to get duration, fps, etc."""
        info = {}

        for cam_id, path in videos.items():
            try:
                result = subprocess.run([
                    "ffprobe",
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    str(path)
                ], capture_output=True, text=True, timeout=30)

                data = json.loads(result.stdout)
                video_stream = next(
                    (s for s in data.get("streams", []) if s["codec_type"] == "video"),
                    {}
                )

                info[cam_id] = {
                    "duration": float(data.get("format", {}).get("duration", 0)),
                    "width": int(video_stream.get("width", 1920)),
                    "height": int(video_stream.get("height", 1080)),
                    "fps": eval(video_stream.get("r_frame_rate", "30/1")),
                    "codec": video_stream.get("codec_name", "unknown"),
                }
            except Exception as e:
                logger.warning(f"Failed to analyze {cam_id}: {e}")
                info[cam_id] = {"error": str(e)}

        return info

    def _stitch_videos(self, job: StitchJob, video_info: Dict):
        """
        Perform the actual video stitching.

        Uses FFmpeg filter_complex for GPU-accelerated processing.
        """
        # Ensure output directory exists
        job.output_path.parent.mkdir(parents=True, exist_ok=True)

        # Get paths in order
        left_path = job.input_videos.get("CAM_L")
        center_path = job.input_videos.get("CAM_C")
        right_path = job.input_videos.get("CAM_R")

        if not all([left_path, center_path, right_path]):
            raise ValueError("Missing one or more camera inputs")

        # Build FFmpeg command for horizontal stacking with blend
        # This creates a simple side-by-side panorama
        # For production, use proper homography warping

        w = 1920
        h = 1080
        overlap = 100
        output_w = 3 * w - 2 * overlap  # 5560

        # Choose encoder
        if self.gpu_available and self.config.stitcher.use_gpu:
            encoder = self.config.stitcher.codec  # h264_nvenc
            encoder_opts = [
                "-c:v", encoder,
                "-preset", "p4",  # Balance speed/quality
                "-rc", "vbr",
                "-cq", "23",
                "-b:v", f"{self.config.stitcher.output_bitrate_mbps}M",
            ]
        else:
            encoder = "libx264"
            encoder_opts = [
                "-c:v", encoder,
                "-preset", "medium",
                "-crf", "23",
            ]

        # FFmpeg filter for blending three videos
        # [0] = left, [1] = center, [2] = right
        filter_complex = f"""
            [0:v]scale={w}:{h}[left];
            [1:v]scale={w}:{h}[center];
            [2:v]scale={w}:{h}[right];
            [left][center]xfade=transition=slideleft:duration=0:offset=0[lc];
            color=black:{output_w}x{h}:d=1[base];
            [base][left]overlay=0:0[tmp1];
            [tmp1][center]overlay={w - overlap}:0[tmp2];
            [tmp2][right]overlay={2*w - 2*overlap}:0[out]
        """.replace("\n", "").replace("  ", "")

        # Simpler approach: just hstack
        filter_simple = f"""
            [0:v]scale={w}:{h}[left];
            [1:v]scale={w}:{h}[center];
            [2:v]scale={w}:{h}[right];
            [left][center][right]hstack=inputs=3[out]
        """.replace("\n", "").replace("  ", "")

        cmd = [
            "ffmpeg", "-y",
            "-i", str(left_path),
            "-i", str(center_path),
            "-i", str(right_path),
            "-filter_complex", filter_simple,
            "-map", "[out]",
            "-map", "1:a?",  # Use center camera audio if present
            *encoder_opts,
            "-movflags", "+faststart",  # Enable seeking
            str(job.output_path)
        ]

        logger.info(f"Running FFmpeg stitch: {' '.join(cmd[:10])}...")

        # Run with progress monitoring
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Monitor progress (simplified)
        _, stderr = process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {stderr[-500:]}")

        # Verify output
        if not job.output_path.exists():
            raise RuntimeError("Output file not created")

        output_size = job.output_path.stat().st_size
        logger.info(f"Stitched video created: {output_size / 1024 / 1024:.1f} MB")


class FrameStitcher:
    """
    Real-time frame stitcher for more advanced blending.

    Uses OpenCV and optionally CUDA for frame-level processing.
    This is slower but produces better results than FFmpeg filters.
    """

    def __init__(self, calibration: CameraCalibration, use_gpu: bool = True):
        self.calibration = calibration
        self.use_gpu = use_gpu and CUPY_AVAILABLE

    def stitch_frame(
        self,
        left: np.ndarray,
        center: np.ndarray,
        right: np.ndarray
    ) -> np.ndarray:
        """
        Stitch three frames into a panorama.

        Args:
            left: Left camera frame (HxWx3)
            center: Center camera frame (HxWx3)
            right: Right camera frame (HxWx3)

        Returns:
            Stitched panorama frame
        """
        if not CV2_AVAILABLE:
            raise RuntimeError("OpenCV required for frame stitching")

        h, w = center.shape[:2]
        overlap = 100
        output_w = 3 * w - 2 * overlap

        # Create output canvas
        panorama = np.zeros((h, output_w, 3), dtype=np.uint8)

        # Place center (no transform needed)
        panorama[:, w - overlap:2*w - overlap] = center

        # Blend left
        blend_region = slice(w - overlap, w)
        for i, x in enumerate(range(w - overlap, w)):
            alpha = i / overlap
            panorama[:, x] = (
                (1 - alpha) * left[:, x - (w - overlap) + (w - overlap)] +
                alpha * panorama[:, x]
            ).astype(np.uint8)
        panorama[:, :w - overlap] = left[:, :w - overlap]

        # Blend right
        right_start = 2 * w - 2 * overlap
        for i, x in enumerate(range(right_start, right_start + overlap)):
            alpha = i / overlap
            panorama[:, x] = (
                (1 - alpha) * panorama[:, x] +
                alpha * right[:, i]
            ).astype(np.uint8)
        panorama[:, right_start + overlap:] = right[:, overlap:]

        return panorama

"""
Audio feedback system for Soccer Rig.

Provides audio cues for:
- Recording start/stop
- Errors and warnings
- Sync events
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import audio libraries
try:
    import simpleaudio as sa
    SIMPLEAUDIO_AVAILABLE = True
except ImportError:
    SIMPLEAUDIO_AVAILABLE = False
    logger.warning("simpleaudio not available - audio feedback disabled")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


class AudioFeedback:
    """
    Audio feedback manager.

    Generates beeps and tones for various system events.
    """

    def __init__(self, config):
        """
        Initialize audio feedback.

        Args:
            config: Configuration with audio settings
        """
        self.config = config
        self._enabled = config.audio.enabled and SIMPLEAUDIO_AVAILABLE and NUMPY_AVAILABLE
        self._volume = config.audio.volume / 100.0
        self._lock = threading.Lock()
        self._sample_rate = 44100

        if self._enabled:
            logger.info("Audio feedback initialized")
        else:
            logger.info("Audio feedback disabled")

    def _generate_tone(
        self,
        frequency: float,
        duration_ms: int,
        volume: Optional[float] = None
    ) -> Optional[bytes]:
        """
        Generate a sine wave tone.

        Args:
            frequency: Tone frequency in Hz
            duration_ms: Duration in milliseconds
            volume: Volume (0.0 to 1.0)

        Returns:
            Audio data as bytes
        """
        if not NUMPY_AVAILABLE:
            return None

        vol = volume if volume is not None else self._volume
        duration_sec = duration_ms / 1000.0

        # Generate sine wave
        t = np.linspace(0, duration_sec, int(self._sample_rate * duration_sec), False)
        tone = np.sin(frequency * t * 2 * np.pi)

        # Apply envelope to avoid clicks
        envelope_samples = int(self._sample_rate * 0.01)  # 10ms envelope
        if len(tone) > envelope_samples * 2:
            # Fade in
            tone[:envelope_samples] *= np.linspace(0, 1, envelope_samples)
            # Fade out
            tone[-envelope_samples:] *= np.linspace(1, 0, envelope_samples)

        # Scale to 16-bit audio
        audio = (tone * vol * 32767).astype(np.int16)

        return audio.tobytes()

    def _play_audio(self, audio_data: bytes) -> None:
        """Play audio data."""
        if not self._enabled or not audio_data:
            return

        try:
            play_obj = sa.play_buffer(
                audio_data,
                num_channels=1,
                bytes_per_sample=2,
                sample_rate=self._sample_rate
            )
            # Don't wait for completion
        except Exception as e:
            logger.error(f"Error playing audio: {e}")

    def _play_async(self, audio_data: bytes) -> None:
        """Play audio in background thread."""
        if audio_data:
            thread = threading.Thread(
                target=self._play_audio,
                args=(audio_data,),
                daemon=True
            )
            thread.start()

    def beep(
        self,
        frequency: float = 800,
        duration_ms: int = 200,
        count: int = 1,
        gap_ms: int = 100
    ) -> None:
        """
        Play a beep tone.

        Args:
            frequency: Tone frequency in Hz
            duration_ms: Duration of each beep in ms
            count: Number of beeps
            gap_ms: Gap between beeps in ms
        """
        if not self._enabled:
            return

        def play_beeps():
            for i in range(count):
                audio = self._generate_tone(frequency, duration_ms)
                self._play_audio(audio)
                if i < count - 1:
                    time.sleep(gap_ms / 1000.0)

        thread = threading.Thread(target=play_beeps, daemon=True)
        thread.start()

    def beep_start(self) -> None:
        """Play recording start beep."""
        if not self.config.audio.beep_on_record_start:
            return
        # Two ascending tones
        self.beep(frequency=600, duration_ms=150)
        time.sleep(0.1)
        self.beep(frequency=900, duration_ms=200)

    def beep_stop(self) -> None:
        """Play recording stop beep."""
        if not self.config.audio.beep_on_record_stop:
            return
        # Two descending tones
        self.beep(frequency=900, duration_ms=150)
        time.sleep(0.1)
        self.beep(frequency=600, duration_ms=200)

    def beep_error(self) -> None:
        """Play error beep."""
        if not self.config.audio.beep_on_error:
            return
        # Three low beeps
        self.beep(frequency=300, duration_ms=200, count=3, gap_ms=150)

    def beep_warning(self) -> None:
        """Play warning beep."""
        # Two medium beeps
        self.beep(frequency=500, duration_ms=150, count=2, gap_ms=100)

    def beep_sync(self) -> None:
        """Play sync beep (for coordinated start)."""
        if not self.config.audio.beep_on_sync:
            return
        # Short high beep
        self.beep(frequency=1200, duration_ms=100)

    def beep_success(self) -> None:
        """Play success beep."""
        # Single pleasant tone
        self.beep(frequency=800, duration_ms=300)

    def beep_low_battery(self) -> None:
        """Play low battery warning."""
        self.beep(frequency=400, duration_ms=500, count=2, gap_ms=200)

    def beep_critical_battery(self) -> None:
        """Play critical battery warning."""
        self.beep(frequency=300, duration_ms=300, count=4, gap_ms=100)

    def beep_temperature_warning(self) -> None:
        """Play temperature warning."""
        self.beep(frequency=600, duration_ms=200, count=3, gap_ms=150)

    def beep_custom(
        self,
        frequency: float = 800,
        duration: float = 0.2,
        count: int = 1
    ) -> None:
        """
        Play a custom beep (convenience wrapper).

        Args:
            frequency: Tone frequency in Hz
            duration: Duration in seconds
            count: Number of beeps
        """
        self.beep(
            frequency=frequency,
            duration_ms=int(duration * 1000),
            count=count,
            gap_ms=100
        )

    def beep_framing_detected(self) -> None:
        """Play field detected beep."""
        self.beep(frequency=600, duration_ms=100)

    def beep_framing_good(self) -> None:
        """Play good framing beep (two quick tones)."""
        self.beep(frequency=800, duration_ms=100, count=2, gap_ms=80)

    def beep_framing_lost(self) -> None:
        """Play framing lost beep."""
        self.beep(frequency=400, duration_ms=200)

    def beep_framing_confirmed(self) -> None:
        """Play framing confirmed beep (rising tones)."""
        if not self._enabled:
            return

        def play():
            for freq in [600, 800, 1000]:
                audio = self._generate_tone(freq, 100)
                self._play_audio(audio)
                time.sleep(0.12)

        thread = threading.Thread(target=play, daemon=True)
        thread.start()

    def play_startup_sound(self) -> None:
        """Play startup sound."""
        if not self._enabled:
            return

        def play():
            # Ascending arpeggio
            for freq in [400, 500, 600, 800]:
                audio = self._generate_tone(freq, 100)
                self._play_audio(audio)
                time.sleep(0.08)

        thread = threading.Thread(target=play, daemon=True)
        thread.start()

    def play_shutdown_sound(self) -> None:
        """Play shutdown sound."""
        if not self._enabled:
            return

        def play():
            # Descending arpeggio
            for freq in [800, 600, 500, 400]:
                audio = self._generate_tone(freq, 100)
                self._play_audio(audio)
                time.sleep(0.08)

        thread = threading.Thread(target=play, daemon=True)
        thread.start()

    def set_volume(self, volume: int) -> None:
        """
        Set audio volume.

        Args:
            volume: Volume level (0-100)
        """
        self._volume = max(0, min(100, volume)) / 100.0
        self.config.audio.volume = volume

    def enable(self) -> None:
        """Enable audio feedback."""
        if SIMPLEAUDIO_AVAILABLE and NUMPY_AVAILABLE:
            self._enabled = True
            self.config.audio.enabled = True

    def disable(self) -> None:
        """Disable audio feedback."""
        self._enabled = False
        self.config.audio.enabled = False

    def is_enabled(self) -> bool:
        """Check if audio is enabled."""
        return self._enabled

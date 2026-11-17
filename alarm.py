import threading
import time
import io
import struct
import math
import ctypes

try:
    import pygame
    pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
    _PYGAME_OK = True
except Exception:
    _PYGAME_OK = False

try:
    import winsound as _winsound
    _WINSOUND_OK = True
except Exception:
    _WINSOUND_OK = False

VK_VOLUME_UP = 0xAF
KEYEVENTF_KEYUP = 0x0002


def _make_wav(hz, duration_ms, volume=0.9, sample_rate=44100):
    """Generate a raw PCM WAV bytes buffer for a sine-wave tone."""
    n_samples = int(sample_rate * duration_ms / 1000)
    header_size = 44
    data_size   = n_samples * 2  # 16-bit mono
    buf = io.BytesIO()
    buf.write(b'RIFF')
    buf.write(struct.pack('<I', header_size - 8 + data_size))
    buf.write(b'WAVE')
    buf.write(b'fmt ')
    buf.write(struct.pack('<IHHIIHH', 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
    buf.write(b'data')
    buf.write(struct.pack('<I', data_size))
    for i in range(n_samples):
        v = int(32767 * volume * math.sin(2 * math.pi * hz * i / sample_rate))
        buf.write(struct.pack('<h', max(-32767, min(32767, v))))
    buf.seek(0)
    return buf.read()


# Pre-synthesize two alarm tones at startup
_HIGH_WAV = _make_wav(2600, 1600)   # 1.6s high tone
_LOW_WAV  = _make_wav(2100, 1600)   # 1.6s low tone

if _PYGAME_OK:
    _snd_high = pygame.mixer.Sound(io.BytesIO(_HIGH_WAV))
    _snd_low  = pygame.mixer.Sound(io.BytesIO(_LOW_WAV))
    _snd_high.set_volume(1.0)
    _snd_low.set_volume(1.0)


class AlarmManager:
    """
    Alarm engine:
    - pygame plays through headphones/speakers regardless of Spotify or other audio.
    - Instant start and instant stop (no blocking winsound.Beep loops).
    """

    def __init__(self, config):
        self.config = config
        self._alarming = False
        self._lock = threading.Lock()
        self._worker = None

    # ── Volume ────────────────────────────────────────────────────────────────
    def crank_to_max_volume_async(self):
        if not self.config.get("blast_max_volume", True):
            return
        def _crank():
            try:
                user32 = ctypes.windll.user32
                for _ in range(50):
                    user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
                    user32.keybd_event(VK_VOLUME_UP, 0, KEYEVENTF_KEYUP, 0)
            except Exception:
                pass
        threading.Thread(target=_crank, daemon=True).start()

    # ── Alarm loop ────────────────────────────────────────────────────────────
    def _alarm_loop(self):
        """Plays alternating BEEEEEP tones until stop_alarm() is called."""
        cycle = 0
        while True:
            with self._lock:
                if not self._alarming:
                    break

            if cycle % 4 == 0:
                self.crank_to_max_volume_async()

            if _PYGAME_OK:
                # High tone 1.6s
                _snd_high.play()
                self._sleep_interruptible(1.65)
                _snd_high.stop()
                if not self._alarming:
                    break

                # 100ms gap
                self._sleep_interruptible(0.1)
                if not self._alarming:
                    break

                # Low tone 1.6s
                _snd_low.play()
                self._sleep_interruptible(1.65)
                _snd_low.stop()
                if not self._alarming:
                    break

                self._sleep_interruptible(0.1)

            elif _WINSOUND_OK:
                # Fallback: winsound (may not play through headphones)
                for _ in range(20):
                    if not self._alarming:
                        break
                    try:
                        _winsound.Beep(2600, 80)
                    except Exception:
                        time.sleep(0.02)
                self._sleep_interruptible(0.1)
                for _ in range(20):
                    if not self._alarming:
                        break
                    try:
                        _winsound.Beep(2100, 80)
                    except Exception:
                        time.sleep(0.02)
                self._sleep_interruptible(0.1)
            else:
                time.sleep(0.5)

            cycle += 1

        # Always silence pygame when loop exits
        if _PYGAME_OK:
            pygame.mixer.stop()

    def _sleep_interruptible(self, seconds):
        """Sleep in small increments so stop_alarm() takes effect within ~50ms."""
        end = time.time() + seconds
        while self._alarming and time.time() < end:
            time.sleep(0.05)

    # ── Public API ────────────────────────────────────────────────────────────
    def start_alarm(self):
        with self._lock:
            if self._alarming:
                return
            self._alarming = True
        self._worker = threading.Thread(target=self._alarm_loop, daemon=True)
        self._worker.start()

    def stop_alarm(self):
        with self._lock:
            self._alarming = False
        if _PYGAME_OK:
            try:
                pygame.mixer.stop()
            except Exception:
                pass

    def is_alarming(self):
        with self._lock:
            return self._alarming

    def shutdown(self):
        self.stop_alarm()

    def play_success_chime(self):
        def _chime():
            time.sleep(0.3)  # brief pause so alarm stops before chime
            if _PYGAME_OK:
                for hz, ms in [(523, 120), (659, 120), (784, 120), (1046, 220)]:
                    snd = pygame.mixer.Sound(io.BytesIO(_make_wav(hz, ms, volume=0.25)))
                    snd.play()
                    time.sleep(ms / 1000 + 0.02)
            elif _WINSOUND_OK:
                for note, dur in [(523, 120), (659, 120), (784, 120), (1046, 220)]:
                    try:
                        _winsound.Beep(note, dur)
                        time.sleep(0.02)
                    except Exception:
                        pass
        threading.Thread(target=_chime, daemon=True).start()

    def play_warning_blip(self):
        def _blip():
            if _PYGAME_OK:
                snd = pygame.mixer.Sound(io.BytesIO(_make_wav(1200, 90, volume=0.6)))
                snd.play()
            elif _WINSOUND_OK:
                try:
                    _winsound.Beep(1200, 90)
                except Exception:
                    pass
        threading.Thread(target=_blip, daemon=True).start()

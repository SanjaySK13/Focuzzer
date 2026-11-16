import threading
import time
import winsound
import ctypes

VK_VOLUME_UP = 0xAF
KEYEVENTF_KEYUP = 0x0002

class AlarmManager:
    """
    Ultra-low-latency alarm manager:
    - Starts sound INSTANTLY when distraction is detected (<50ms).
    - Cuts sound OFF INSTANTLY when returning to study tabs (<80ms).
    - Sustained BEEEEEP blasts (1.6s long continuous tones) by chaining ultra-short 80ms slices.
    """
    def __init__(self, config):
        self.config = config
        self._alarm_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._worker_thread = threading.Thread(target=self._audio_worker_loop, daemon=True)
        self._worker_thread.start()

    def crank_to_max_volume_async(self):
        """Asynchronously cranks volume so audio playback is NEVER delayed."""
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

    def _audio_worker_loop(self):
        while not self._shutdown_event.is_set():
            # Wait until alarm is signaled
            if not self._alarm_event.wait(timeout=0.05):
                continue

            # Crank volume in parallel without stalling sound start
            self.crank_to_max_volume_async()

            cycle = 0
            while self._alarm_event.is_set() and not self._shutdown_event.is_set():
                if cycle % 2 == 0:
                    self.crank_to_max_volume_async()
                cycle += 1

                # BLAST 1: Sustained High Siren (2600 Hz) - 1.6s continuous BEEEEEEEP!
                # 20 ultra-short slices of 80ms with 0 delay = continuous tone,
                # but stops within ~0.08s the millisecond you switch back!
                for _ in range(20):
                    if not self._alarm_event.is_set() or self._shutdown_event.is_set():
                        break
                    try:
                        winsound.Beep(2600, 80)
                    except Exception:
                        time.sleep(0.02)

                if not self._alarm_event.is_set() or self._shutdown_event.is_set():
                    break

                # 100ms breath gap between blasts
                time.sleep(0.1)

                # BLAST 2: Sustained Piercing Tone (2100 Hz) - 1.6s continuous BEEEEEEEP!
                for _ in range(20):
                    if not self._alarm_event.is_set() or self._shutdown_event.is_set():
                        break
                    try:
                        winsound.Beep(2100, 80)
                    except Exception:
                        time.sleep(0.02)

                if not self._alarm_event.is_set() or self._shutdown_event.is_set():
                    break

                time.sleep(0.1)

    def start_alarm(self):
        """Immediately signals the worker to start beeping."""
        self._alarm_event.set()

    def stop_alarm(self):
        """Immediately silences the alarm."""
        self._alarm_event.clear()

    def is_alarming(self):
        return self._alarm_event.is_set()

    def shutdown(self):
        self._alarm_event.clear()
        self._shutdown_event.set()

    def play_success_chime(self):
        def _chime():
            for note, dur in [(523, 120), (659, 120), (784, 120), (1046, 220)]:
                try:
                    winsound.Beep(note, dur)
                    time.sleep(0.02)
                except Exception:
                    pass
        threading.Thread(target=_chime, daemon=True).start()

    def play_warning_blip(self):
        def _blip():
            try:
                winsound.Beep(1200, 90)
            except Exception:
                pass
        threading.Thread(target=_blip, daemon=True).start()

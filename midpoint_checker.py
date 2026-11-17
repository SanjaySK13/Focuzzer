import tkinter as tk
import time

class MidpointCheckerDialog:
    """
    Small, compact on-screen checker that pops up randomly at (Session Duration / 2) ± 10 seconds.
    Forces a quick active verification that the user is still on task.
    """
    def __init__(self, parent, session_minutes, timeout_seconds, alarm_manager, on_confirmed):
        self.parent = parent
        self.session_minutes = session_minutes
        self.timeout_seconds = timeout_seconds
        self.alarm_manager = alarm_manager
        self.on_confirmed = on_confirmed
        
        self.remaining_seconds = timeout_seconds
        self.confirmed = False
        self._timer_id = None

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Focuzzer - Midpoint Focus Check")
        self.dialog.attributes("-topmost", True)
        self.dialog.configure(bg="#0A0F1E")

        # Small, compact geometry (390 x 210)
        w, h = 390, 210
        sw = self.dialog.winfo_screenwidth()
        sh = self.dialog.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.dialog.geometry(f"{w}x{h}+{x}+{y}")
        self.dialog.resizable(False, False)

        self.dialog.protocol("WM_DELETE_WINDOW", self._on_attempt_close)

        self._build_ui()
        self.alarm_manager.play_warning_blip()
        self._tick()

    def _build_ui(self):
        # Outer card frame with indigo border
        border = tk.Frame(self.dialog, bg="#6366F1", bd=2)
        border.pack(fill="both", expand=True)

        inner = tk.Frame(border, bg="#111827", padx=16, pady=12)
        inner.pack(fill="both", expand=True)

        # Header row
        hdr = tk.Frame(inner, bg="#111827")
        hdr.pack(fill="x", pady=(0, 4))

        tk.Label(
            hdr,
            text="⚡ MIDPOINT CHECK",
            font=("Segoe UI", 9, "bold"),
            bg="#312E81",
            fg="#C7D2FE",
            padx=8,
            pady=2
        ).pack(side="left")

        self.lbl_countdown = tk.Label(
            hdr,
            text=f"{self.remaining_seconds}s",
            font=("Consolas", 10, "bold"),
            bg="#111827",
            fg="#F59E0B"
        )
        self.lbl_countdown.pack(side="right")

        # Prompt text
        tk.Label(
            inner,
            text="Halfway through session! Quick check:",
            font=("Segoe UI", 11, "bold"),
            bg="#111827",
            fg="#F9FAFB"
        ).pack(anchor="w", pady=(6, 1))

        tk.Label(
            inner,
            text="Are you actively on task and studying right now?",
            font=("Segoe UI", 9),
            bg="#111827",
            fg="#9CA3AF"
        ).pack(anchor="w", pady=(0, 10))

        # Big Confirm Button
        self.btn_confirm = tk.Button(
            inner,
            text="✓ YES, STILL STUDYING!",
            font=("Segoe UI", 11, "bold"),
            bg="#22C55E",
            fg="#000000",
            activebackground="#16A34A",
            activeforeground="#000000",
            relief="flat",
            pady=8,
            cursor="hand2",
            command=self._confirm
        )
        self.btn_confirm.pack(fill="x")

        # Hotkeys for 1-key instant dismissal
        self.dialog.bind("<Return>", lambda e: self._confirm())
        self.dialog.bind("<space>", lambda e: self._confirm())
        self.btn_confirm.focus_set()

    def _tick(self):
        if self.confirmed or not self.dialog.winfo_exists():
            return

        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self.lbl_countdown.config(
                text=f"{self.remaining_seconds}s",
                fg="#EF4444" if self.remaining_seconds <= 8 else "#F59E0B"
            )
            self.dialog.lift()
            self.dialog.attributes("-topmost", True)
            self._timer_id = self.dialog.after(1000, self._tick)
        else:
            # Timed out — just show ALARM label; the main tick loop
            # (focus_guard._tick) sees midpoint_timed_out=True and starts alarm.
            # Do NOT call start_alarm() here to avoid double-alarm overlap.
            self.lbl_countdown.config(text="ALARM!", fg="#EF4444")
            self.dialog.lift()
            self.dialog.attributes("-topmost", True)
            self._timer_id = self.dialog.after(1000, self._tick)

    def _confirm(self):
        if self.confirmed:
            return
        self.confirmed = True

        if self._timer_id:
            try:
                self.dialog.after_cancel(self._timer_id)
            except Exception:
                pass

        self.alarm_manager.stop_alarm()
        self.alarm_manager.play_success_chime()
        self.on_confirmed()

        if self.dialog.winfo_exists():
            self.dialog.destroy()

    def _on_attempt_close(self):
        self.alarm_manager.play_warning_blip()

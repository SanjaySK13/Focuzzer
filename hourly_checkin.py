import tkinter as tk
from tkinter import ttk
import time

class HourlyCheckinDialog:
    def __init__(self, parent, hour_num, timeout_seconds, alarm_manager, on_confirmed):
        self.parent = parent
        self.hour_num = hour_num
        self.timeout_seconds = timeout_seconds
        self.alarm_manager = alarm_manager
        self.on_confirmed = on_confirmed
        self.remaining_seconds = timeout_seconds
        self.confirmed = False
        self._timer_id = None
        
        # Create TopLevel window
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Focuzzer - Hourly Check-in")
        self.dialog.attributes("-topmost", True)
        self.dialog.configure(bg="#0F172A")
        
        # Center dialog
        w, h = 500, 330
        screen_w = self.dialog.winfo_screenwidth()
        screen_h = self.dialog.winfo_screenheight()
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        self.dialog.geometry(f"{w}x{h}+{x}+{y}")
        self.dialog.resizable(False, False)
        
        # Prevent closing via [X]
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_attempt_close)
        
        self._build_ui()
        
        # Play alert blip
        self.alarm_manager.play_warning_blip()
        
        # Start countdown ticker
        self._tick()

    def _build_ui(self):
        main_frame = tk.Frame(self.dialog, bg="#0F172A", padx=24, pady=20)
        main_frame.pack(fill="both", expand=True)

        # Icon / Header
        lbl_icon = tk.Label(main_frame, text="⏰", font=("Segoe UI Emoji", 36), bg="#0F172A", fg="#F59E0B")
        lbl_icon.pack(pady=(0, 4))

        lbl_title = tk.Label(
            main_frame, 
            text=f"HOURLY FOCUS CHECK-IN #{self.hour_num}", 
            font=("Segoe UI", 16, "bold"), 
            bg="#0F172A", 
            fg="#F8FAFC"
        )
        lbl_title.pack()

        lbl_subtitle = tk.Label(
            main_frame,
            text=f"You have been studying for {self.hour_num} hour{'s' if self.hour_num > 1 else ''}!\nAre you still actively on task and studying?",
            font=("Segoe UI", 10),
            bg="#0F172A",
            fg="#94A3B8",
            justify="center"
        )
        lbl_subtitle.pack(pady=8)

        # Countdown label
        self.lbl_countdown = tk.Label(
            main_frame,
            text=f"Confirm within {self.remaining_seconds}s or alarm will blast!",
            font=("Segoe UI", 11, "bold"),
            bg="#0F172A",
            fg="#F59E0B"
        )
        self.lbl_countdown.pack(pady=4)

        # Big Confirm Button
        self.btn_confirm = tk.Button(
            main_frame,
            text="✓ YES, I AM ACTIVELY STUDYING!",
            font=("Segoe UI", 12, "bold"),
            bg="#10B981",
            fg="#FFFFFF",
            activebackground="#059669",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=20,
            pady=10,
            cursor="hand2",
            command=self._confirm
        )
        self.btn_confirm.pack(fill="x", pady=(12, 0))
        
        # Bind Enter and Space keys for instant one-key confirmation!
        self.dialog.bind("<Return>", lambda e: self._confirm())
        self.dialog.bind("<space>", lambda e: self._confirm())
        self.btn_confirm.focus_set()

    def _tick(self):
        if self.confirmed or not self.dialog.winfo_exists():
            return

        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self.lbl_countdown.config(
                text=f"Confirm within {self.remaining_seconds}s or ALARM will blast!",
                fg="#EF4444" if self.remaining_seconds <= 15 else "#F59E0B"
            )
            # Re-assert topmost and front position
            self.dialog.lift()
            self.dialog.attributes("-topmost", True)
            self._timer_id = self.dialog.after(1000, self._tick)
        else:
            # Time expired — just show warning; focus_guard._tick sees checkin_timed_out
            # and starts alarm centrally. No direct start_alarm() here to avoid overlap.
            self.lbl_countdown.config(
                text="🚨 TIME EXPIRED! CLICK BELOW TO CONFIRM & STOP ALARM!",
                fg="#EF4444"
            )
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
        # Prevent dismissing via Alt+F4 or window management without clicking confirm
        self.alarm_manager.play_warning_blip()

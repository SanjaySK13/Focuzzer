import tkinter as tk
from tkinter import messagebox
import time
import ctypes
from emergency_dialog import EmergencyUnlockDialog

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ─── Colour palette ──────────────────────────────────────────────────────────
BG_DARK    = "#0A0F1E"
BG_CARD    = "#111827"
ACCENT     = "#6366F1"       # indigo-500
GREEN      = "#22C55E"
AMBER      = "#F59E0B"
RED        = "#EF4444"
RED_DEEP   = "#7F1D1D"
TEXT_HI    = "#F9FAFB"
TEXT_MID   = "#9CA3AF"
TEXT_DIM   = "#4B5563"

class OverlayHUD:
    def __init__(self, root, target_seconds, config, alarm_manager, on_session_end):
        self.root            = root
        self.target_seconds  = target_seconds
        self.config          = config
        self.alarm_manager   = alarm_manager
        self.on_session_end  = on_session_end

        self.start_time       = time.time()
        self.session_done     = False
        self.drag_offset_x    = 0
        self.drag_offset_y    = 0

        self.hud_w = 820
        self.hud_h = 64

        self.root.title("Focuzzer")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=ACCENT)          # 2-px accent border shows through

        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"{self.hud_w}x{self.hud_h}+{(sw - self.hud_w)//2}+16")

        self.warning_win  = None
        self._warn_flash  = False   # for red-flash toggle

        self._build()
        self._bind_drag()
        self.root.protocol("WM_DELETE_WINDOW", self._attempt_close)

    # ─── Build HUD ────────────────────────────────────────────────────────────
    def _build(self):
        # 2-px indigo border is the root bg; inner frame is dark
        self.inner = tk.Frame(self.root, bg=BG_CARD, padx=14, pady=0)
        self.inner.pack(fill="both", expand=True, padx=2, pady=2)

        # LEFT — status dot + labels
        left = tk.Frame(self.inner, bg=BG_CARD)
        left.pack(side="left", fill="y")

        self.dot = tk.Label(left, text="●", font=("Segoe UI", 18, "bold"),
                            bg=BG_CARD, fg=GREEN)
        self.dot.pack(side="left", padx=(0, 8))

        label_col = tk.Frame(left, bg=BG_CARD)
        label_col.pack(side="left", fill="y", pady=10)

        self.lbl_status = tk.Label(label_col, text="FOCUSED",
                                   font=("Segoe UI", 10, "bold"),
                                   bg=BG_CARD, fg=GREEN)
        self.lbl_status.pack(anchor="w")

        self.lbl_detail = tk.Label(label_col, text="Monitoring active windows…",
                                   font=("Segoe UI", 8), bg=BG_CARD, fg=TEXT_MID)
        self.lbl_detail.pack(anchor="w")

        # CENTER — big clock
        center = tk.Frame(self.inner, bg=BG_CARD)
        center.pack(side="left", expand=True)

        self.lbl_clock = tk.Label(center, text="00:00:00",
                                  font=("Consolas", 18, "bold"),
                                  bg=BG_CARD, fg=TEXT_HI)
        self.lbl_clock.pack()

        self.lbl_lock = tk.Label(center, text="🔒 Calculating…",
                                 font=("Segoe UI", 7, "bold"),
                                 bg=BG_CARD, fg=AMBER)
        self.lbl_lock.pack()

        # RIGHT — action buttons
        right = tk.Frame(self.inner, bg=BG_CARD)
        right.pack(side="right", padx=(0, 4))

        self.btn_off = tk.Button(
            right,
            text="🔒  Locked",
            font=("Segoe UI", 9, "bold"),
            bg=TEXT_DIM, fg=BG_DARK,
            activebackground=TEXT_DIM, activeforeground=BG_DARK,
            relief="flat", padx=14, pady=5,
            state=tk.DISABLED,
            cursor="arrow",
            command=self._switch_off
        )
        self.btn_off.pack(side="left", padx=4)

        self.btn_emerg = tk.Button(
            right,
            text="⚠️ Quit Challenge",
            font=("Segoe UI", 8, "bold"),
            bg="#312E81", fg="#E0E7FF",
            activebackground="#4338CA", activeforeground="#FFFFFF",
            relief="flat", padx=8, pady=5,
            cursor="hand2",
            command=self._emergency
        )
        self.btn_emerg.pack(side="left")

    # ─── Drag ─────────────────────────────────────────────────────────────────
    def _bind_drag(self):
        def _start(e):
            self.drag_offset_x = e.x_root - self.root.winfo_x()
            self.drag_offset_y = e.y_root - self.root.winfo_y()

        def _move(e):
            nx = max(0, min(e.x_root - self.drag_offset_x,
                            self.root.winfo_screenwidth()  - self.hud_w))
            ny = max(0, min(e.y_root - self.drag_offset_y,
                            self.root.winfo_screenheight() - self.hud_h))
            self.root.geometry(f"+{nx}+{ny}")

        for w in [self.root, self.inner, self.lbl_clock, self.lbl_lock,
                  self.lbl_status, self.lbl_detail, self.dot]:
            w.bind("<Button-1>", _start)
            w.bind("<B1-Motion>", _move)

    # ─── Timer update (called every 500 ms) ───────────────────────────────────
    def update_timers(self):
        if not self.root.winfo_exists():
            return

        elapsed   = time.time() - self.start_time
        remaining = max(0.0, self.target_seconds - elapsed)

        self.lbl_clock.config(text=time.strftime("%H:%M:%S", time.gmtime(elapsed)))

        self.root.lift()
        self.root.attributes("-topmost", True)

        if remaining > 0:
            rem_str = time.strftime("%H:%M:%S", time.gmtime(remaining))
            self.lbl_lock.config(text=f"🔒  Unlocks in {rem_str}", fg=AMBER)
            self.btn_off.config(text=f"🔒  Locked  {rem_str}",
                                state=tk.DISABLED,
                                bg=TEXT_DIM, fg=BG_DARK, cursor="arrow")
        else:
            if not self.session_done:
                self.session_done = True
                self.alarm_manager.play_success_chime()
            self.lbl_lock.config(text="🎉  Target reached — you may now stop", fg=GREEN)
            self.btn_off.config(text="🛑  End Session",
                                state=tk.NORMAL,
                                bg=GREEN, fg="#000000",
                                activebackground="#16A34A", activeforeground="#000000",
                                cursor="hand2")

    # ─── Focus state update ───────────────────────────────────────────────────
    def update_focus_state(self, ev):
        if not self.root.winfo_exists():
            return

        st      = ev["status"]
        reason  = ev.get("reason", "")
        matched = ev.get("matched_item", "?")
        title   = ev.get("title", "")
        short   = (title[:36] + "…") if len(title) > 36 else title

        if st == "allowed":
            self.inner.config(bg=BG_CARD)
            self.dot.config(fg=GREEN, bg=BG_CARD)
            self.lbl_status.config(text=f"FOCUSED — {matched}", fg=GREEN, bg=BG_CARD)
            self.lbl_detail.config(text=short or "On-task", fg=TEXT_MID, bg=BG_CARD)
            self._hide_warning()

        elif st == "warning":
            gl = int(ev.get("grace_time_left", 0))
            self.inner.config(bg="#1C1200")
            self.dot.config(fg=AMBER, bg="#1C1200")
            self.lbl_status.config(text=f"NEW TAB — {gl}s to navigate",
                                   fg=AMBER, bg="#1C1200")
            self.lbl_detail.config(text="Open NotebookLM, Gemini, or WhatsApp",
                                   fg="#FDE68A", bg="#1C1200")
            self._hide_warning()

        elif st == "violation":
            self.inner.config(bg="#1A0000")
            self.dot.config(fg=RED, bg="#1A0000")
            self.lbl_status.config(text="⛔  DISTRACTION DETECTED", fg=RED, bg="#1A0000")
            self.lbl_detail.config(text=short or "Forbidden window", fg="#FCA5A5", bg="#1A0000")
            self._show_warning(short, reason)

    # ─── BIG Warning Banner ───────────────────────────────────────────────────
    def _show_warning(self, site_title, reason):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        # Banner is WIDE and TALL — impossible to miss
        bw, bh = sw - 60, 220
        bx = 30
        by = (sh - bh) // 2        # vertically centered on screen

        if self.warning_win is None or not self.warning_win.winfo_exists():
            self.warning_win = tk.Toplevel(self.root)
            self.warning_win.overrideredirect(True)
            self.warning_win.attributes("-topmost", True)
            self.warning_win.geometry(f"{bw}x{bh}+{bx}+{by}")
            self.warning_win.configure(bg=RED)

            # Thick red inner frame
            inner = tk.Frame(self.warning_win, bg=RED_DEEP, bd=0)
            inner.pack(fill="both", expand=True, padx=6, pady=6)

            # Giant alarm header
            tk.Label(inner, text="⛔  STOP. GET BACK TO STUDYING!  ⛔",
                     font=("Segoe UI", 24, "bold"),
                     bg=RED_DEEP, fg="#FEE2E2").pack(pady=(26, 6))

            self.lbl_warn_site = tk.Label(inner,
                     text="",
                     font=("Segoe UI", 15, "bold"),
                     bg=RED_DEEP, fg="#FDE68A",
                     wraplength=bw - 80)
            self.lbl_warn_site.pack(pady=(0, 6))

            tk.Label(inner,
                     text="Allowed: NotebookLM  |  Gemini  |  WhatsApp",
                     font=("Segoe UI", 12, "bold"),
                     bg=RED_DEEP, fg="#FCA5A5").pack()

        # Always update text & re-flash
        self.warning_win.lift()
        self.warning_win.attributes("-topmost", True)
        self.lbl_warn_site.config(text=reason)
        self._flash_warning()

    def _flash_warning(self):
        """Toggle banner background between two reds so it pulses."""
        if self.warning_win is None or not self.warning_win.winfo_exists():
            return
        self._warn_flash = not self._warn_flash
        col = "#DC2626" if self._warn_flash else RED_DEEP
        self.warning_win.configure(bg=col)
        # Schedule next flash only if still alarming
        if self.alarm_manager.is_alarming():
            self.root.after(400, self._flash_warning)

    def _hide_warning(self):
        if self.warning_win and self.warning_win.winfo_exists():
            self.warning_win.destroy()
        self.warning_win = None

    # ─── Buttons ──────────────────────────────────────────────────────────────
    def _switch_off(self):
        if self.session_done:
            self._hide_warning()
            self.on_session_end(normal_exit=True)

    def _emergency(self):
        EmergencyUnlockDialog(self.root, self._emergency_confirmed)

    def _emergency_confirmed(self):
        self._hide_warning()
        self.alarm_manager.stop_alarm()
        self.on_session_end(normal_exit=False)

    def _attempt_close(self):
        if self.session_done:
            self._switch_off()
        else:
            self._emergency()

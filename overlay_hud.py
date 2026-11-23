import tkinter as tk
from tkinter import messagebox
import time
import ctypes
from math import sqrt
from emergency_dialog import EmergencyUnlockDialog
from appearance import GLASS, GLASS_EDGE, apple_color, round_rect, rounded_window_region, style_widgets, style_window

TRANSPARENT_CORNER = "#ff00fe"

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
        self.apple           = config.get("appearance") == "apple"
        self.alarm_manager   = alarm_manager
        self.on_session_end  = on_session_end

        self.start_time       = time.time()
        self.session_done     = False
        self.drag_offset_x    = 0
        self.drag_offset_y    = 0

        self.root.title("Focuzzer")
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=ACCENT)          # 2-px accent border shows through

        self.warning_win  = None

        self._build()
        if self.apple:
            style_widgets(self.inner, True)
        self.root.update_idletasks()
        self.hud_w = max(760 if self.apple else 820, self.inner.winfo_reqwidth() + 88)
        self.hud_h = max(92 if self.apple else 78, self.inner.winfo_reqheight() + (28 if self.apple else 12))
        sw = self.root.winfo_screenwidth()
        self.hud_w = min(self.hud_w, sw - 24)
        self.root.geometry(f"{self.hud_w}x{self.hud_h}+{(sw - self.hud_w)//2}+16")
        if self.apple:
            self._draw_glass()
            self.root.update_idletasks()
            rounded_window_region(self.root, self.hud_w, self.hud_h, self.hud_h)
            style_window(self.root, True, animate=True, opacity=0.88)
        self._bind_drag()
        self.root.protocol("WM_DELETE_WINDOW", self._attempt_close)
        self.root.deiconify()

    # ─── Build HUD ────────────────────────────────────────────────────────────
    def _build(self):
        # 2-px indigo border is the root bg; inner frame is dark
        self.inner = tk.Frame(self.root, bg=BG_CARD, padx=14, pady=0)
        if self.apple:
            self.root.configure(bg=TRANSPARENT_CORNER)
            self.root.attributes("-transparentcolor", TRANSPARENT_CORNER)
            self.pill = tk.Canvas(self.root, bg=TRANSPARENT_CORNER, highlightthickness=0)
            self.pill.place(relwidth=1, relheight=1)
            self.inner.pack(fill="both", expand=True, padx=35, pady=(12, 16))
            self.inner.lift()
        else:
            self.inner.pack(fill="both", expand=True, padx=2, pady=2)

        # LEFT — status dot + labels
        left = tk.Frame(self.inner, bg=BG_CARD)
        left.pack(side="left", padx=(0, 14))

        self.dot = tk.Label(left, text="●", font=("Segoe UI", 18, "bold"),
                            bg=BG_CARD, fg=GREEN)
        self.dot.pack(side="left", padx=(0, 8))

        label_col = tk.Frame(left, bg=BG_CARD)
        label_col.pack(side="left")

        self.lbl_status = tk.Label(label_col, text="Focused" if self.apple else "FOCUSED",
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
                                  font=("Segoe UI" if self.apple else "Consolas", 18, "bold"),
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
            text="Quit early" if self.apple else "⚠️ Quit Challenge",
            font=("Segoe UI", 8, "bold"),
            bg="#312E81", fg="#E0E7FF",
            activebackground="#4338CA", activeforeground="#FFFFFF",
            relief="flat", padx=8, pady=5,
            cursor="hand2",
            command=self._emergency
        )
        self.btn_emerg.pack(side="left")

    def _draw_glass(self):
        radius = (self.hud_h - 2) / 2
        for y in range(2, self.hud_h - 1):
            inset = radius - sqrt(radius ** 2 - (y - self.hud_h / 2) ** 2)
            light = max(0, 12 - y)
            color = f"#{32 + light * 2:02x}{36 + light * 2:02x}{45 + light * 3:02x}"
            self.pill.create_line(inset + 1, y, self.hud_w - inset - 1, y, fill=color)
        self.pill.create_arc(1, 1, self.hud_h - 1, self.hud_h - 1,
                             start=90, extent=180, style="arc", outline=GLASS_EDGE, tags="pill")
        self.pill.create_arc(self.hud_w - self.hud_h + 1, 1, self.hud_w - 1, self.hud_h - 1,
                             start=-90, extent=180, style="arc", outline=GLASS_EDGE, tags="pill")
        self.pill.create_line(radius + 1, 1, self.hud_w - radius - 1, 1,
                              fill="#8c99ad", tags="pill_edge")
        self.pill.create_line(radius + 1, self.hud_h - 1, self.hud_w - radius - 1,
                              self.hud_h - 1, fill=GLASS_EDGE, tags="pill_edge")
        y = self.hud_h - 9
        self.pill.create_line(45, y, self.hud_w - 45, y, fill=GLASS_EDGE, capstyle="round")
        self.progress = self.pill.create_line(45, y, 45, y, fill="#76a9ff", width=2, capstyle="round")

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

        handles = [self.root, self.inner, self.lbl_clock, self.lbl_lock,
                   self.lbl_status, self.lbl_detail, self.dot]
        if self.apple:
            handles.append(self.pill)
        for w in handles:
            w.bind("<Button-1>", _start)
            w.bind("<B1-Motion>", _move)

    # ─── Timer update (called every 500 ms) ───────────────────────────────────
    def update_timers(self):
        if not self.root.winfo_exists():
            return

        elapsed   = time.time() - self.start_time
        remaining = max(0.0, self.target_seconds - elapsed)

        self.lbl_clock.config(text=time.strftime("%H:%M:%S", time.gmtime(elapsed)))
        if self.apple:
            fraction = 1 - remaining / self.target_seconds
            y = self.hud_h - 9
            self.pill.coords(self.progress, 45, y, 45 + fraction * (self.hud_w - 90), y)

        if remaining > 0:
            rem_str = time.strftime("%H:%M:%S", time.gmtime(remaining))
            self.lbl_lock.config(text=f"Unlocks in {rem_str}" if self.apple else f"🔒  Unlocks in {rem_str}", fg=AMBER)
            self.btn_off.config(text="End session" if self.apple else f"🔒  Locked  {rem_str}",
                                state=tk.DISABLED,
                                bg=apple_color(TEXT_DIM) if self.apple else TEXT_DIM,
                                fg=BG_DARK, cursor="arrow")
        else:
            if not self.session_done:
                self.session_done = True
                # Stop any active alarm first, then play soft chime after a moment
                self.alarm_manager.stop_alarm()
                self.alarm_manager.play_success_chime()
            self.lbl_lock.config(text="Goal reached" if self.apple else "🎉  Target reached — you may now stop", fg=GREEN)
            self.btn_off.config(text="End session" if self.apple else "🛑  End Session",
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
        card_bg = GLASS if self.apple else BG_CARD
        warning_bg = GLASS if self.apple else "#1C1200"
        danger_bg = GLASS if self.apple else "#1A0000"
        if self.apple and st != "neutral":
            edge = {"warning": AMBER, "violation": RED}.get(st, GLASS_EDGE)
            self.pill.itemconfigure("pill", outline=edge)

        if st == "allowed":
            self.inner.config(bg=card_bg)
            self.dot.config(fg=GREEN, bg=card_bg)
            self.lbl_status.config(text=f"Focused · {matched}" if self.apple else f"FOCUSED — {matched}",
                                   fg=GREEN, bg=card_bg)
            self.lbl_detail.config(text=short or "On-task", fg=TEXT_MID, bg=card_bg)
            self._hide_warning()

        elif st == "warning":
            gl = int(ev.get("grace_time_left", 0))
            self.inner.config(bg=warning_bg)
            self.dot.config(fg=AMBER, bg=warning_bg)
            self.lbl_status.config(text=f"NEW TAB — {gl}s to navigate",
                                   fg=AMBER, bg=warning_bg)
            self.lbl_detail.config(text="Open NotebookLM, Gemini, or WhatsApp",
                                   fg="#FDE68A", bg=warning_bg)
            self._hide_warning()

        elif st == "checking":
            self.inner.config(bg=card_bg)
            self.dot.config(fg=AMBER, bg=card_bg)
            self.lbl_status.config(text="CHECKING BROWSER", fg=AMBER, bg=card_bg)
            self.lbl_detail.config(text=short, fg=TEXT_MID, bg=card_bg)
            self._hide_warning()

        elif st == "violation":
            self.inner.config(bg=danger_bg)
            self.dot.config(fg=RED, bg=danger_bg)
            self.lbl_status.config(text="Off task" if self.apple else "⛔  DISTRACTION DETECTED",
                                   fg=RED, bg=danger_bg)
            self.lbl_detail.config(text=short or "Forbidden window", fg="#FCA5A5", bg=danger_bg)
            self._show_warning(short, reason)

    # ─── BIG Warning Banner ───────────────────────────────────────────────────
    def _show_warning(self, site_title, reason):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        bw, bh = (min(590, sw - 60), 136) if self.apple else (sw - 60, 220)
        bx = (sw - bw) // 2
        by = (sh - bh) // 2

        if self.warning_win is None or not self.warning_win.winfo_exists():
            self.warning_win = tk.Toplevel(self.root)
            self.warning_win.withdraw()
            self.warning_win.title("Focuzzer - Distraction Warning")
            self.warning_win.overrideredirect(True)
            self.warning_win.attributes("-topmost", True)
            self.warning_win.geometry(f"{bw}x{bh}+{bx}+{by}")
            background = GLASS if self.apple else RED_DEEP
            if self.apple:
                self.warning_win.configure(bg=TRANSPARENT_CORNER)
                self.warning_win.attributes("-transparentcolor", TRANSPARENT_CORNER)
                canvas = tk.Canvas(self.warning_win, bg=TRANSPARENT_CORNER, highlightthickness=0)
                canvas.place(relwidth=1, relheight=1)
                round_rect(canvas, 1, 1, bw - 1, bh - 1, 26, fill=GLASS, outline=RED)
                style_window(self.warning_win, True, animate=True)
            else:
                self.warning_win.configure(bg=RED)
            inner = tk.Frame(self.warning_win, bg=background, bd=0)
            inner.pack(fill="both", expand=True, padx=22 if self.apple else 6, pady=6)

            # Giant alarm header
            tk.Label(inner, text="Return to your study session" if self.apple else "⛔  STOP. GET BACK TO STUDYING!  ⛔",
                     font=("Segoe UI", 16 if self.apple else 24, "bold"),
                     bg=background, fg="#FEE2E2").pack(pady=(18 if self.apple else 26, 6))

            self.lbl_warn_site = tk.Label(inner,
                     text="",
                     font=("Segoe UI", 11 if self.apple else 15, "bold"),
                     bg=background, fg="#FDE68A",
                     wraplength=bw - 80)
            self.lbl_warn_site.pack(pady=(0, 6))

            tk.Label(inner,
                     text="Allowed: NotebookLM  |  Gemini  |  WhatsApp",
                     font=("Segoe UI", 12, "bold"),
                     bg=background, fg="#FCA5A5").pack()
            self.warning_win.deiconify()

        self.lbl_warn_site.config(text=reason)
        if not self.apple:
            col = "#DC2626" if int(time.monotonic() / 0.4) % 2 else RED_DEEP
            self.warning_win.configure(bg=col)

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
        EmergencyUnlockDialog(self.root, self._emergency_confirmed, apple=self.apple)

    def _emergency_confirmed(self):
        self._hide_warning()
        self.alarm_manager.stop_alarm()
        self.on_session_end(normal_exit=False)

    def _attempt_close(self):
        if self.session_done:
            self._switch_off()
        else:
            self._emergency()

"""
focus_guard.py  —  Focuzzer main window
Tabs:  [Start Session]  [Study History]
"""
import tkinter as tk
from tkinter import ttk, messagebox
import time
import json
import os
import sys
import random

from config import load_config, save_config, append_study_history, apply_custom_whitelisted_urls, HISTORY_FILE
from alarm import AlarmManager
from window_tracker import WindowTracker
from overlay_hud import OverlayHUD
from hourly_checkin import HourlyCheckinDialog
from midpoint_checker import MidpointCheckerDialog

# ─── Colour palette (matches HUD) ────────────────────────────────────────────
BG       = "#0A0F1E"
BG_CARD  = "#111827"
BG_ROW   = "#1F2937"
BG_ROW2  = "#17202E"
ACCENT   = "#6366F1"
GREEN    = "#22C55E"
AMBER    = "#F59E0B"
RED      = "#EF4444"
TEXT_HI  = "#F9FAFB"
TEXT_MID = "#9CA3AF"
TEXT_DIM = "#4B5563"

def _btn(parent, text, cmd, color=ACCENT, fg="#FFFFFF", **kwargs):
    """Factory for clean flat buttons."""
    b = tk.Button(
        parent, text=text, command=cmd,
        font=("Segoe UI", 10, "bold"),
        bg=color, fg=fg,
        activebackground=_darken(color), activeforeground=fg,
        relief="flat", padx=16, pady=8,
        cursor="hand2",
        **kwargs
    )
    b.bind("<Enter>", lambda e: b.config(bg=_darken(color)))
    b.bind("<Leave>", lambda e: b.config(bg=color))
    return b

def _darken(hex_col):
    """15% darkening of a hex colour."""
    try:
        r = max(0, int(hex_col[1:3], 16) - 25)
        g = max(0, int(hex_col[3:5], 16) - 25)
        b = max(0, int(hex_col[5:7], 16) - 25)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_col

class FocusGuardApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Focuzzer - Hardcore Study Lock")
        self.root.configure(bg=BG)

        # High-DPI awareness
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # Adaptive window geometry
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(720, sw - 40)
        h = min(730, sh - 60)
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.root.minsize(600, 620)
        self.root.resizable(True, True)

        self.config         = load_config()
        self.alarm_manager  = AlarmManager(self.config)
        self.window_tracker = WindowTracker(self.config)

        # Session runtime state
        self.session_active       = False
        self.target_seconds       = 3600
        self.start_timestamp      = 0
        self.last_checkin_ts      = 0
        self.distraction_count    = 0
        self.checkin_count        = 0
        self.active_checkin       = None
        self.hud                  = None
        self._mon_id              = None

        # State tracking to fix count bug & midpoint checker
        self._in_violation_state  = False
        self.midpoint_target_sec  = 0
        self.midpoint_triggered   = False
        self.active_midpoint      = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)

    # =========================================================================
    # UI BUILD
    # =========================================================================
    def _build_ui(self):
        # ── Top accent stripe & title bar ─────────────────────────────────────
        hdr = tk.Frame(self.root, bg=ACCENT, height=3)
        hdr.pack(fill="x")

        title_bar = tk.Frame(self.root, bg=BG, padx=20, pady=10)
        title_bar.pack(fill="x")

        tk.Label(title_bar, text="🛡  Focuzzer",
                 font=("Segoe UI", 16, "bold"),
                 bg=BG, fg=TEXT_HI).pack(side="left")

        tk.Label(title_bar, text="Hardcore Study Sentinel",
                 font=("Segoe UI", 9), bg=BG, fg=TEXT_MID).pack(side="left", padx=10, pady=2)

        # ── Tab bar ───────────────────────────────────────────────────────────
        self.notebook = ttk.Notebook(self.root)
        self._style_notebook()
        self.notebook.pack(fill="both", expand=True, padx=0, pady=0)

        # Tab frames
        self.tab_session = tk.Frame(self.notebook, bg=BG)
        self.tab_history = tk.Frame(self.notebook, bg=BG)

        self.notebook.add(self.tab_session, text="  ▶  New Session  ")
        self.notebook.add(self.tab_history, text="  📊  Study History  ")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

        self._build_session_tab()
        self._build_history_tab()

    def _style_notebook(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab",
                        background=BG_CARD, foreground=TEXT_MID,
                        font=("Segoe UI", 9, "bold"),
                        padding=[14, 6])
        style.map("TNotebook.Tab",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", TEXT_HI)])

    # ─── Session tab ──────────────────────────────────────────────────────────
    def _build_session_tab(self):
        s = self.tab_session

        # ── CRITICAL: BOTTOM-DOCKED LAUNCH BUTTON ─────────────────────────────
        # Docked at the bottom FIRST so it is mathematically impossible to clip!
        btn_frame = tk.Frame(s, bg=BG, padx=20, pady=12)
        btn_frame.pack(side="bottom", fill="x")

        self.btn_launch = tk.Button(
            btn_frame,
            text="🚀  START HARDCORE STUDY SESSION",
            font=("Segoe UI", 12, "bold"),
            bg=ACCENT,
            fg="#FFFFFF",
            activebackground="#4F46E5",
            activeforeground="#FFFFFF",
            relief="flat",
            pady=11,
            cursor="hand2",
            command=self._start_session
        )
        self.btn_launch.pack(fill="x")
        self.btn_launch.bind("<Enter>", lambda e: self.btn_launch.config(bg="#4F46E5"))
        self.btn_launch.bind("<Leave>", lambda e: self.btn_launch.config(bg=ACCENT))

        # ── Top Content Frame (fits cleanly above the button) ────────────────
        content = tk.Frame(s, bg=BG, padx=20, pady=4)
        content.pack(side="top", fill="both", expand=True)

        pad = dict(fill="x", pady=(0, 8))

        # ── Card 1: Duration ──────────────────────────────────────────────────
        self._card_header(content, "1  —  Choose Study Commitment Duration")

        dur_card = tk.Frame(content, bg=BG_CARD, padx=16, pady=10)
        dur_card.pack(**pad)

        tk.Label(dur_card,
                 text="🔒  Switch-off button stays LOCKED until this timer runs out.",
                 font=("Segoe UI", 8, "bold"), bg=BG_CARD, fg=AMBER).pack(anchor="w", pady=(0, 6))

        self.duration_var = tk.IntVar(value=60)

        preset_row = tk.Frame(dur_card, bg=BG_CARD)
        preset_row.pack(fill="x", pady=(0, 4))

        for label, mins in [("30 min", 30), ("45 min", 45), ("1 hr", 60),
                             ("1.5 hr", 90), ("2 hr", 120), ("3 hr", 180)]:
            rb = tk.Radiobutton(
                preset_row, text=label, value=mins,
                variable=self.duration_var,
                font=("Segoe UI", 9, "bold"),
                bg=BG_CARD, fg=TEXT_HI,
                selectcolor=BG_ROW,
                activebackground=BG_CARD, activeforeground=ACCENT,
                cursor="hand2",
                command=self._preset_chosen
            )
            rb.pack(side="left", expand=True)

        custom_row = tk.Frame(dur_card, bg=BG_CARD)
        custom_row.pack(fill="x", pady=(4, 0))

        tk.Label(custom_row, text="Or Custom Duration (minutes):",
                 font=("Segoe UI", 9), bg=BG_CARD, fg=TEXT_MID).pack(side="left")

        self.entry_custom = tk.Entry(
            custom_row,
            font=("Consolas", 10), width=8,
            bg=BG_ROW, fg=TEXT_HI,
            insertbackground=TEXT_HI,
            relief="flat", bd=3
        )
        self.entry_custom.pack(side="left", padx=8)

        # ── Card 2: Allowed Whitelist ─────────────────────────────────────────
        self._card_header(content, "2  —  Whitelisted Sites & Custom URLs")

        wl_card = tk.Frame(content, bg=BG_CARD, padx=16, pady=8)
        wl_card.pack(**pad)

        sites_grid = tk.Frame(wl_card, bg=BG_CARD)
        sites_grid.pack(fill="x")

        # Left Column
        col_left = tk.Frame(sites_grid, bg=BG_CARD)
        col_left.pack(side="left", fill="x", expand=True)
        for text in ["✓ NotebookLM (notebooklm.google.com)", "✓ Gemini (gemini.google.com)"]:
            tk.Label(col_left, text=text, font=("Segoe UI", 9, "bold"),
                     bg=BG_CARD, fg=GREEN).pack(anchor="w", pady=1)

        # Right Column
        col_right = tk.Frame(sites_grid, bg=BG_CARD)
        col_right.pack(side="left", fill="x", expand=True)
        for text in ["✓ WhatsApp (Web & Desktop App)", "✓ Local Notes (VS Code, PDF, Obsidian, Notion)"]:
            tk.Label(col_right, text=text, font=("Segoe UI", 9, "bold" if "WhatsApp" in text else "normal"),
                     bg=BG_CARD, fg=GREEN if "WhatsApp" in text else TEXT_MID).pack(anchor="w", pady=1)

        extra_row = tk.Frame(wl_card, bg=BG_CARD)
        extra_row.pack(fill="x", pady=(6, 0))
        
        # Enhanced label explaining URLs can be pasted
        tk.Label(extra_row, text="Whitelist Custom URLs / Sites (e.g. discord.com, leetcode.com, claude.ai):",
                 font=("Segoe UI", 8, "bold"), bg=BG_CARD, fg="#A5B4FC").pack(anchor="w")
        
        self.entry_extra = tk.Entry(
            extra_row,
            font=("Segoe UI", 9), bg=BG_ROW, fg=TEXT_HI,
            insertbackground=TEXT_HI, relief="flat", bd=3
        )
        self.entry_extra.pack(fill="x", pady=(2, 0))
        
        # Pre-fill with previously saved custom URLs so user doesn't have to retype!
        saved_urls = self.config.get("custom_extra_input", "")
        if saved_urls:
            self.entry_extra.insert(0, saved_urls)

        # ── Card 3: Enforcement Options ───────────────────────────────────────
        self._card_header(content, "3  —  Addiction Breaker Settings")

        opt_card = tk.Frame(content, bg=BG_CARD, padx=16, pady=8)
        opt_card.pack(**pad)

        self.var_vol    = tk.BooleanVar(value=self.config.get("blast_max_volume", True))
        self.var_hourly = tk.BooleanVar(value=True)

        for var, txt, col in [
            (self.var_vol,    "Force 100% volume & blast long piercing alarms (BEEEEEEP BEEEEEEP)", RED),
            (self.var_hourly, "Hourly check-in prompt + Random Midpoint Focus Checker", TEXT_HI),
        ]:
            tk.Checkbutton(
                opt_card, text=txt, variable=var,
                font=("Segoe UI", 9, "bold"),
                bg=BG_CARD, fg=col,
                selectcolor=BG_ROW,
                activebackground=BG_CARD, activeforeground=col
            ).pack(anchor="w", pady=1)

    def _card_header(self, parent, text):
        tk.Label(parent, text=text,
                 font=("Segoe UI", 8, "bold"),
                 bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(6, 2))

    # ─── History tab ──────────────────────────────────────────────────────────
    def _build_history_tab(self):
        h = self.tab_history

        # ── Summary strip ─────────────────────────────────────────────────────
        self.summary_frame = tk.Frame(h, bg=BG_CARD, padx=16, pady=10)
        self.summary_frame.pack(fill="x", padx=20, pady=(12, 6))

        # ── Table header ──────────────────────────────────────────────────────
        self._card_header(h, "Recent Study Sessions")

        tree_wrap = tk.Frame(h, bg=BG, padx=20, pady=0)
        tree_wrap.pack(fill="both", expand=True)

        cols = ("Date", "Target", "Actual", "Result", "Distractions", "Check-ins")
        style = ttk.Style()
        style.configure("FG.Treeview",
                        background=BG_ROW, fieldbackground=BG_ROW,
                        foreground=TEXT_HI, rowheight=26,
                        font=("Segoe UI", 9))
        style.configure("FG.Treeview.Heading",
                        background=BG_CARD, foreground=TEXT_MID,
                        font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("FG.Treeview", background=[("selected", ACCENT)])

        self.tree = ttk.Treeview(tree_wrap, columns=cols, show="headings",
                                 style="FG.Treeview", height=10)

        col_widths = [160, 75, 75, 75, 100, 85]
        for col, w in zip(cols, col_widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="center", stretch=True)

        sb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

        self.tree.tag_configure("even", background=BG_ROW)
        self.tree.tag_configure("odd",  background=BG_ROW2)
        self.tree.tag_configure("ok",   foreground=GREEN)
        self.tree.tag_configure("bail", foreground=AMBER)

        # ── Button row ────────────────────────────────────────────────────────
        btn_row = tk.Frame(h, bg=BG, padx=20, pady=10)
        btn_row.pack(fill="x")

        _btn(btn_row, "↻  Refresh", self._load_history,
             color=BG_CARD, fg=TEXT_HI).pack(side="left")
        _btn(btn_row, "🗑  Clear History", self._clear_history,
             color="#374151", fg=TEXT_HI).pack(side="right")

        self._load_history()

    def _load_history(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        history = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                pass

        for w in self.summary_frame.winfo_children():
            w.destroy()

        real = [s for s in history if not s.get("test")]
        total_sessions = len(real)
        total_min      = sum(s.get("actual_duration_seconds", 0) for s in real) // 60
        total_distr    = sum(s.get("distractions_blocked", 0) for s in real)
        completed      = sum(1 for s in real if s.get("completed_cleanly"))

        for label, value, col in [
            ("Total Sessions", str(total_sessions), TEXT_HI),
            ("Total Study Time", f"{total_min // 60}h {total_min % 60}m", GREEN),
            ("Completed", str(completed), GREEN),
            ("Distractions Blocked", str(total_distr), RED),
        ]:
            box = tk.Frame(self.summary_frame, bg=BG_ROW, padx=14, pady=6)
            box.pack(side="left", padx=(0, 8), fill="x", expand=True)
            tk.Label(box, text=value, font=("Segoe UI", 14, "bold"),
                     bg=BG_ROW, fg=col).pack()
            tk.Label(box, text=label, font=("Segoe UI", 8),
                     bg=BG_ROW, fg=TEXT_MID).pack()

        for i, s in enumerate(reversed(real)):
            target_m   = s.get("target_duration_mins", 0)
            actual_s   = s.get("actual_duration_seconds", 0)
            actual_str = f"{actual_s // 60}m {actual_s % 60}s"
            done       = "✓ Completed" if s.get("completed_cleanly") else "✗ Quit Early"
            distr      = str(s.get("distractions_blocked", 0))
            checks     = str(s.get("hourly_checkins_completed", 0))
            date       = s.get("date", "—")

            tag_row  = "even" if i % 2 == 0 else "odd"
            tag_done = "ok" if s.get("completed_cleanly") else "bail"

            self.tree.insert("", "end",
                             values=(date, f"{target_m}m", actual_str,
                                     done, distr, checks),
                             tags=(tag_row, tag_done))

    def _clear_history(self):
        if messagebox.askyesno("Clear History",
                               "Delete all study history records permanently?",
                               parent=self.root):
            try:
                with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                    json.dump([], f)
            except Exception:
                pass
            self._load_history()

    def _on_tab_change(self, _event=None):
        idx = self.notebook.index("current")
        if idx == 1:
            self._load_history()

    # =========================================================================
    # SESSION LOGIC
    # =========================================================================
    def _preset_chosen(self):
        self.entry_custom.delete(0, tk.END)

    def _start_session(self):
        # Duration validation
        custom = self.entry_custom.get().strip()
        if custom:
            try:
                mins = int(custom)
                if not 1 <= mins <= 1440:
                    raise ValueError
                self.target_seconds = mins * 60
            except ValueError:
                messagebox.showerror("Invalid Duration",
                                     "Enter a positive number between 1 and 1440 minutes.",
                                     parent=self.root)
                return
        else:
            self.target_seconds = self.duration_var.get() * 60

        # CRITICAL: Apply and expand all custom whitelisted URLs/keywords (e.g. discord.com)
        raw_extra = self.entry_extra.get().strip()
        expanded_kws = apply_custom_whitelisted_urls(self.config, raw_extra)

        self.config["blast_max_volume"] = self.var_vol.get()
        save_config(self.config)

        # Refresh tracker's config so new whitelisted keywords are live
        self.window_tracker.config = self.config

        # Confirm lock commitment
        h_str = f"{self.target_seconds // 3600}h {(self.target_seconds % 3600) // 60}m"
        wl_summary = "NotebookLM, Gemini, WhatsApp"
        if raw_extra:
            wl_summary += f", {raw_extra}"

        if not messagebox.askyesno(
                "Lock In?",
                f"You are locking your computer into Study Mode for {h_str}.\n\n"
                f"• Whitelisted: {wl_summary}\n"
                "• Other sites: Piercing alarm blasts (BEEEEEP BEEEEEEP)\n"
                "• Switch-off button is LOCKED until time expires\n"
                "• Early quit requires typing a 26-character jumbled code\n\n"
                "Ready to commit?",
                parent=self.root):
            return

        # Launch
        self.root.withdraw()
        self.session_active       = True
        self.start_timestamp      = time.time()
        self.last_checkin_ts      = self.start_timestamp
        self.distraction_count    = 0
        self.checkin_count        = 0
        self._in_violation_state  = False

        # Midpoint checker calculation: (Duration / 2) ± 10 seconds
        half_sec = self.target_seconds / 2.0
        jitter = random.uniform(-10.0, 10.0)
        self.midpoint_target_sec = max(5.0, min(self.target_seconds - 5.0, half_sec + jitter))
        self.midpoint_triggered  = False
        self.active_midpoint     = None

        hud_win  = tk.Toplevel(self.root)
        self.hud = OverlayHUD(hud_win, self.target_seconds,
                              self.config, self.alarm_manager,
                              self._end_session)
        self._tick()

    def _tick(self):
        if not self.session_active:
            return

        now = time.time()
        elapsed = now - self.start_timestamp

        if self.hud:
            self.hud.update_timers()

        # ── 1. Midpoint Focus Checker: (Halfway ± 10s) ───────────────────────
        if self.var_hourly.get() and not self.midpoint_triggered and elapsed >= self.midpoint_target_sec:
            self.midpoint_triggered = True
            if self.hud and self.hud.root.winfo_exists():
                self.active_midpoint = MidpointCheckerDialog(
                    self.hud.root,
                    self.target_seconds // 60,
                    25,  # 25 seconds to confirm before alarm sounds
                    self.alarm_manager,
                    self._midpoint_done
                )

        # ── 2. Hourly Check-in Trigger (Every 3600s) ─────────────────────────
        if self.var_hourly.get() and (now - self.last_checkin_ts >= 3600):
            if self.active_checkin is None:
                self.checkin_count += 1
                if self.hud and self.hud.root.winfo_exists():
                    self.active_checkin = HourlyCheckinDialog(
                        self.hud.root,
                        self.checkin_count,
                        int(self.config.get("hourly_checkin_timeout_seconds", 60)),
                        self.alarm_manager,
                        self._checkin_done
                    )

        # ── 3. Ultra-Low-Latency Continuous Focus Window Evaluation ──────────
        ev = self.window_tracker.evaluate_focus()
        if self.hud:
            self.hud.update_focus_state(ev)

        # Is a midpoint/check-in modal currently demanding attention?
        checkin_timed_out  = (self.active_checkin  is not None
                              and self.active_checkin.remaining_seconds  <= 0)
        midpoint_timed_out = (self.active_midpoint is not None
                              and self.active_midpoint.remaining_seconds <= 0)
        modal_alarm_active = checkin_timed_out or midpoint_timed_out

        if ev["status"] == "violation":
            # Count ONLY ONCE per distraction episode!
            if not self._in_violation_state:
                self._in_violation_state = True
                self.distraction_count += 1

            # Only start tab-violation alarm if no modal alarm is already sounding
            if not self.alarm_manager.is_alarming() and not modal_alarm_active:
                self.alarm_manager.start_alarm()

        else:
            # Bug fix: clicking the Focuzzer pill makes it the foreground window (allowed)
            # while still on a restricted site — don't stop alarm or reset violation state.
            is_focuzzer_focus = ev.get("matched_item", "") in ("Focuzzer", "System")
            if is_focuzzer_focus and self._in_violation_state:
                pass  # keep alarm running, don't reset state
            else:
                self._in_violation_state = False
                # Silence tab-violation alarm; leave modal alarms alone
                if not modal_alarm_active and self.alarm_manager.is_alarming():
                    self.alarm_manager.stop_alarm()

        # Fast 100ms polling for INSTANT (<0.1s) tab switch detection
        self._mon_id = self.root.after(100, self._tick)

    def _midpoint_done(self):
        self.active_midpoint = None

    def _checkin_done(self):
        self.last_checkin_ts = time.time()
        self.active_checkin  = None

    def _end_session(self, normal_exit=True):
        self.session_active = False
        if self._mon_id:
            try:
                self.root.after_cancel(self._mon_id)
            except Exception:
                pass

        self.alarm_manager.stop_alarm()

        if self.hud:
            try:
                self.hud.root.destroy()
            except Exception:
                pass
            self.hud = None

        total   = int(time.time() - self.start_timestamp)
        mins, s = divmod(total, 60)

        record = {
            "date":                      time.strftime("%Y-%m-%d %H:%M:%S"),
            "target_duration_mins":      self.target_seconds // 60,
            "actual_duration_seconds":   total,
            "distractions_blocked":      self.distraction_count,
            "hourly_checkins_completed": self.checkin_count,
            "completed_cleanly":         normal_exit,
        }
        append_study_history(record)

        self.root.deiconify()
        # Switch to history tab so user sees their record
        self.notebook.select(1)
        self._load_history()

        if normal_exit:
            self.alarm_manager.play_success_chime()
            messagebox.showinfo(
                "Session Complete 🎉",
                f"You achieved your study goal!\n\n"
                f"⏱  Total Study Time  :  {mins}m {s}s\n"
                f"🚫  Distraction Episodes Blocked  :  {self.distraction_count}\n"
                f"⏰  Check-ins Passed  :  {self.checkin_count}\n\n"
                "Saved to Study History.",
                parent=self.root)
        else:
            messagebox.showwarning(
                "Session Overridden",
                f"Study session ended early via jumbled challenge.\n\n"
                f"⏱  Time Studied  :  {mins}m {s}s\n"
                f"🚫  Distraction Episodes  :  {self.distraction_count}",
                parent=self.root)

    def _on_exit(self):
        self.session_active = False
        self.alarm_manager.shutdown()
        self.root.destroy()

def main():
    root = tk.Tk()
    FocusGuardApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()

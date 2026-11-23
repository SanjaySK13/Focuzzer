import tkinter as tk
import random
import string
from appearance import style_dialog

# Unambiguous characters (excludes easily confused: 0, O, o, 1, l, I)
CHALLENGE_CHARS = "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ!@#$%&*?="

def generate_jumbled_string(length=26):
    """Generates a random, jumbled line of characters, numbers, and symbols."""
    # Ensure at least 3 symbols, 5 numbers, 5 uppercase, 5 lowercase
    symbols = "!@#$%&*?="
    numbers = "23456789"
    upper = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    lower = "abcdefghjkmnpqrstuvwxyz"
    
    mandatory = [
        random.choice(symbols), random.choice(symbols), random.choice(symbols),
        random.choice(numbers), random.choice(numbers),
        random.choice(upper), random.choice(upper),
        random.choice(lower), random.choice(lower)
    ]
    remaining = [random.choice(CHALLENGE_CHARS) for _ in range(length - len(mandatory))]
    combined = mandatory + remaining
    random.shuffle(combined)
    return "".join(combined)

class EmergencyUnlockDialog:
    def __init__(self, parent, on_unlock_granted, *, apple=False):
        self.parent = parent
        self.on_unlock_granted = on_unlock_granted
        self.target_phrase = generate_jumbled_string(26)
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.withdraw()
        self.dialog.title("Focuzzer - Quit Verification Challenge")
        self.dialog.attributes("-topmost", True)
        self.dialog.configure(bg="#0B0F19")
        
        self._build_ui()
        self.dialog.update_idletasks()
        # Size from the actual font metrics and button heights at this DPI.
        w, h = self.dialog.winfo_reqwidth(), self.dialog.winfo_reqheight()
        screen_w = self.dialog.winfo_screenwidth()
        screen_h = self.dialog.winfo_screenheight()
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        self.dialog.geometry(f"{w}x{h}+{x}+{y}")
        self.dialog.resizable(False, False)

        style_dialog(self.dialog, apple)
        self.dialog.deiconify()
        self.entry.focus_set()

    def _build_ui(self):
        frame = tk.Frame(self.dialog, bg="#0B0F19", padx=24, pady=20)
        frame.pack(fill="both", expand=True)

        # Header Badge
        header_row = tk.Frame(frame, bg="#0B0F19")
        header_row.pack(fill="x", pady=(0, 6))

        lbl_badge = tk.Label(
            header_row,
            text="⚠️ QUIT VERIFICATION",
            font=("Segoe UI", 9, "bold"),
            bg="#7F1D1D",
            fg="#FEE2E2",
            padx=8,
            pady=2
        )
        lbl_badge.pack(side="left")

        lbl_anti_cheat = tk.Label(
            header_row,
            text="🔒 Copy & Paste Disabled",
            font=("Segoe UI", 8, "bold"),
            bg="#1E293B",
            fg="#94A3B8",
            padx=8,
            pady=2
        )
        lbl_anti_cheat.pack(side="right")

        lbl_title = tk.Label(
            frame,
            text="Type The Jumbled Line To Quit",
            font=("Segoe UI", 16, "bold"),
            bg="#0B0F19",
            fg="#F8FAFC"
        )
        lbl_title.pack(anchor="w", pady=(4, 2))

        lbl_desc = tk.Label(
            frame,
            text="To end the session early, type the code exactly as shown. Capital letters matter.",
            font=("Segoe UI", 10),
            wraplength="340p",
            bg="#0B0F19",
            fg="#94A3B8",
            justify="left"
        )
        lbl_desc.pack(anchor="w", pady=(0, 12))

        # Jumbled string display box
        target_container = tk.Frame(frame, bg="#1E1B4B", bd=2, relief="solid")
        target_container.pack(fill="x", pady=(4, 14))

        code_header = tk.Frame(target_container, bg="#1E1B4B", padx=10, pady=4)
        code_header.pack(fill="x")

        tk.Label(
            code_header,
            text="REQUIRED JUMBLED LINE (CASE SENSITIVE):",
            font=("Segoe UI", 8, "bold"),
            bg="#1E1B4B",
            fg="#A5B4FC"
        ).pack(side="left")

        btn_regen = tk.Button(
            code_header,
            text="↻ New Code",
            font=("Segoe UI", 8, "bold"),
            bg="#312E81",
            fg="#E0E7FF",
            activebackground="#4338CA",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
            command=self._regenerate_code
        )
        btn_regen.pack(side="right")

        self.lbl_target = tk.Label(
            target_container,
            text=self.target_phrase,
            font=("Consolas", 14, "bold"),
            bg="#1E1B4B",
            fg="#FDE047",
            padx=12,
            pady=10,
            justify="center"
        )
        self.lbl_target.pack(fill="x")

        # Typing entry
        lbl_type_prompt = tk.Label(
            frame,
            text="Type the line here (Manual typing only):",
            font=("Segoe UI", 9, "bold"),
            bg="#0B0F19",
            fg="#E2E8F0"
        )
        lbl_type_prompt.pack(anchor="w", pady=(0, 5))

        self.entry_var = tk.StringVar()
        self.entry_var.trace_add("write", self._on_text_change)

        self.entry = tk.Entry(
            frame,
            textvariable=self.entry_var,
            font=("Consolas", 13, "bold"),
            bg="#0F172A",
            fg="#F8FAFC",
            insertbackground="#FFFFFF",
            relief="solid",
            bd=1,
            highlightthickness=2,
            highlightbackground="#334155",
            highlightcolor="#6366F1"
        )
        self.entry.pack(fill="x", ipady=6, pady=(0, 6))

        # BLOCK ALL PASTE SHORTCUTS AND RIGHT-CLICK
        self.entry.bind("<Control-v>", lambda e: "break")
        self.entry.bind("<Control-V>", lambda e: "break")
        self.entry.bind("<Shift-Insert>", lambda e: "break")
        self.entry.bind("<<Paste>>", lambda e: "break")
        self.entry.bind("<Button-3>", lambda e: "break")

        # Status & character counter
        status_row = tk.Frame(frame, bg="#0B0F19")
        status_row.pack(fill="x", pady=(2, 20))

        self.lbl_status = tk.Label(
            status_row,
            text="Start typing to match the jumbled characters...",
            font=("Segoe UI", 9),
            bg="#0B0F19",
            fg="#94A3B8"
        )
        self.lbl_status.pack(side="left")

        self.lbl_counter = tk.Label(
            status_row,
            text=f"0 / {len(self.target_phrase)}",
            font=("Consolas", 9, "bold"),
            bg="#0B0F19",
            fg="#64748B"
        )
        self.lbl_counter.pack(side="right")

        # Action Buttons
        btn_box = tk.Frame(frame, bg="#0B0F19")
        btn_box.pack(fill="x")

        btn_cancel = tk.Button(
            btn_box,
            text="✓ KEEP STUDYING",
            font=("Segoe UI", 10, "bold"),
            bg="#10B981",
            fg="#FFFFFF",
            activebackground="#059669",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=18,
            pady=10,
            cursor="hand2",
            command=self.dialog.destroy
        )
        btn_cancel.pack(side="left")

        self.btn_quit = tk.Button(
            btn_box,
            text="🛑 QUIT SESSION",
            font=("Segoe UI", 10, "bold"),
            bg="#1E293B",
            fg="#64748B",
            relief="flat",
            padx=18,
            pady=10,
            state=tk.DISABLED,
            cursor="arrow",
            command=self._confirm_quit
        )
        self.btn_quit.pack(side="right")

    def _regenerate_code(self):
        self.target_phrase = generate_jumbled_string(26)
        self.lbl_target.config(text=self.target_phrase)
        self.entry_var.set("")
        self.entry.focus_set()

    def _on_text_change(self, *args):
        typed = self.entry_var.get()
        target = self.target_phrase
        curr_len = len(typed)
        target_len = len(target)

        self.lbl_counter.config(text=f"{curr_len} / {target_len}")

        if not typed:
            self.lbl_status.config(text="Start typing to match the jumbled characters...", fg="#94A3B8")
            self.entry.config(highlightbackground="#334155", highlightcolor="#6366F1")
            self._set_quit_enabled(False)
            return

        if typed == target:
            # 100% Exact match!
            self.lbl_status.config(text="✓ CHALLENGE VERIFIED! You may quit now.", fg="#10B981")
            self.lbl_counter.config(fg="#10B981")
            self.entry.config(highlightbackground="#10B981", highlightcolor="#10B981")
            self._set_quit_enabled(True)
        elif target.startswith(typed):
            # Correct so far!
            rem = target_len - curr_len
            self.lbl_status.config(text=f"Correct so far! {rem} character{'s' if rem > 1 else ''} remaining...", fg="#38BDF8")
            self.lbl_counter.config(fg="#38BDF8")
            self.entry.config(highlightbackground="#38BDF8", highlightcolor="#38BDF8")
            self._set_quit_enabled(False)
        else:
            # Mistake!
            self.lbl_status.config(text="Mismatch. Backspace to correct it.", fg="#EF4444")
            self.lbl_counter.config(fg="#EF4444")
            self.entry.config(highlightbackground="#EF4444", highlightcolor="#EF4444")
            self._set_quit_enabled(False)

    def _set_quit_enabled(self, enabled):
        if enabled:
            self.btn_quit.config(
                state=tk.NORMAL,
                bg="#E11D48",
                fg="#FFFFFF",
                activebackground="#BE123C",
                activeforeground="#FFFFFF",
                cursor="hand2"
            )
        else:
            self.btn_quit.config(
                state=tk.DISABLED,
                bg="#1E293B",
                fg="#64748B",
                cursor="arrow"
            )

    def _confirm_quit(self):
        if self.entry_var.get() == self.target_phrase:
            self.dialog.destroy()
            self.on_unlock_granted()

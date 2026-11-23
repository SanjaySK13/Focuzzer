"""Shared visual treatment for Focuzzer's Apple style."""

import ctypes
import tkinter as tk


GLASS = "#20242d"
GLASS_EDGE = "#525a69"
GLASS_HIGHLIGHT = "#383f4c"
APPLE_COLORS = {
    "#0a0f1e": "#14171e",
    "#0b0f19": "#14171e",
    "#0f172a": GLASS,
    "#111827": GLASS,
    "#1f2937": "#2b313c",
    "#17202e": "#252a34",
    "#312e81": "#323a49",
    "#1e1b4b": "#303746",
    "#6366f1": "#2866d9",
    "#4f46e5": "#2058bd",
    "#4338ca": "#404c60",
    "#9ca3af": "#b9c0cc",
    "#a5b4fc": "#aacfff",
    "#4b5563": "#3a414e",
}


def apple_color(color):
    return APPLE_COLORS.get(str(color).lower(), color)


def style_widgets(widget, apple):
    """Switch existing Tk widgets in place, keeping their values and focus."""
    options = (
        "background", "foreground", "activebackground", "activeforeground",
        "selectcolor", "insertbackground", "highlightbackground", "highlightcolor",
    )
    if not hasattr(widget, "_basic_colors"):
        supported = widget.keys()
        widget._basic_colors = {
            key: widget.cget(key) for key in options if key in supported
        }
    widget._apple_style = apple
    widget.configure(**{
        key: apple_color(value) if apple else value
        for key, value in widget._basic_colors.items()
    })
    for child in widget.winfo_children():
        style_widgets(child, apple)
    if hasattr(widget, "_draw_surface"):
        widget._draw_surface()


def surface(parent, background, card, **pack_options):
    wrapper = tk.Frame(parent, bg=background)
    wrapper.pack(**pack_options)
    canvas = tk.Canvas(wrapper, bg=background, highlightthickness=0)
    canvas.place(relwidth=1, relheight=1)
    body = tk.Frame(wrapper, bg=card)
    body.pack(fill="x", padx=16, pady=9)

    def draw(_event=None):
        canvas.delete("surface")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if getattr(wrapper, "_apple_style", False):
            round_rect(canvas, 1, 1, width - 1, height - 1, 16,
                       fill=GLASS, outline=GLASS_HIGHLIGHT, tags="surface")
        else:
            canvas.create_rectangle(0, 0, width, height, fill=card,
                                    width=0, tags="surface")

    wrapper._draw_surface = draw
    canvas.bind("<Configure>", draw)
    return body


def round_rect(canvas, x1, y1, x2, y2, radius, **options):
    points = (
        x1, y1 + radius, x1, y1, x1 + radius, y1,
        x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2,
        x1 + radius, y2, x1, y2, x1, y2 - radius,
    )
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **options)


def rounded_window_region(window, width, height, diameter):
    """Clip the native wrapper as well as the Tk surface."""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetParent.argtypes = [ctypes.c_void_p]
    user32.GetParent.restype = ctypes.c_void_p
    gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
    user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    hwnd = user32.GetParent(window.winfo_id())
    region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, diameter, diameter)
    if not region:
        return False
    if user32.SetWindowRgn(hwnd, region, True):
        return True
    gdi32.DeleteObject(region)
    return False


def style_window(window, apple, animate=False, opacity=0.97):
    """Apply Windows corner hints and ease in the glass surface."""
    pending = getattr(window, "_appearance_timer", None)
    if pending is not None:
        window.after_cancel(pending)
        window._appearance_timer = None

    try:
        get_parent = ctypes.windll.user32.GetParent
        get_parent.argtypes = [ctypes.c_void_p]
        get_parent.restype = ctypes.c_void_p
        hwnd = get_parent(window.winfo_id())
        preference = ctypes.c_int(1 if window.overrideredirect() else 2 if apple else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 33, ctypes.byref(preference), ctypes.sizeof(preference)
        )
    except (AttributeError, OSError):
        pass

    if not apple or not animate or not animations_enabled():
        window.attributes("-alpha", opacity if apple else 1.0)
        return

    if not hasattr(window, "_appearance_timer"):
        window._appearance_timer = None
        def cancel_fade(event):
            if event.widget is window and window._appearance_timer is not None:
                window.after_cancel(window._appearance_timer)
                window._appearance_timer = None
        window.bind("<Destroy>", cancel_fade, add="+")

    def fade(step):
        progress = 1 - (1 - step / 10) ** 3
        window.attributes("-alpha", 0.70 + (opacity - 0.70) * progress)
        window._appearance_timer = window.after(16, fade, step + 1) if step < 10 else None

    fade(0)


def animations_enabled():
    """Honor the Windows Animation Effects setting."""
    try:
        enabled = ctypes.c_int()
        success = ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(enabled), 0
        )
        return bool(enabled.value) if success else True
    except (AttributeError, OSError):
        return True


def style_dialog(dialog, apple):
    if apple:
        style_widgets(dialog, True)
        style_window(dialog, True, animate=True)


def glass_prompt(parent, kind, title, message):
    """Show a modal prompt while preserving the meaning of the native buttons."""
    dialog = tk.Toplevel(parent)
    dialog.withdraw()
    dialog.title(f"Focuzzer - {title}")
    dialog.transient(parent)
    dialog.resizable(False, False)
    dialog.configure(bg="#0a0f1e")
    card = surface(dialog, "#0a0f1e", "#111827", fill="both", padx=12, pady=12)
    tk.Label(card, text=title, bg="#111827", fg="#f9fafb",
             font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(5, 8))
    tk.Label(card, text=message, bg="#111827", fg="#9ca3af",
             font=("Segoe UI", 10), wraplength=410, justify="left").pack(anchor="w")
    actions = tk.Frame(card, bg="#111827")
    actions.pack(fill="x", pady=(16, 4))
    confirmed = False

    def close(answer=False):
        nonlocal confirmed
        confirmed = answer
        dialog.destroy()

    def button(text, answer, color):
        control = tk.Button(actions, text=text, command=lambda: close(answer),
                            bg=color, fg="#f9fafb", activeforeground="#f9fafb",
                            activebackground="#4f46e5", relief="flat", padx=16, pady=6)
        control.pack(side="right", padx=(8, 0))
        return control

    if kind == "askyesno":
        button("Yes", True, "#6366f1")
        default = button("No", False, "#1f2937")
    else:
        default = button("OK", True, "#6366f1")
    dialog.bind("<Escape>", lambda _event: close())
    dialog.bind("<Return>", lambda _event: dialog.focus_get().invoke()
                if isinstance(dialog.focus_get(), tk.Button) else None)
    dialog.protocol("WM_DELETE_WINDOW", close)
    dialog.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - dialog.winfo_reqwidth()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - dialog.winfo_reqheight()) // 2
    dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
    style_dialog(dialog, True)
    dialog.deiconify()
    dialog.wait_visibility()
    dialog.grab_set()
    default.focus_set()
    dialog.wait_window()
    return confirmed

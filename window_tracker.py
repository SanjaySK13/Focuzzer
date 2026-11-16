import time
import ctypes
import re
import os

try:
    import win32gui
    import win32process
    import psutil
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

class WindowTracker:
    def __init__(self, config):
        self.config = config
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        
        # Track when user entered a "New Tab" or neutral state for grace period
        self.grace_start_time = None

    def get_foreground_window_info(self):
        """Returns (hwnd, window_title, process_name) safely without crashing."""
        try:
            hwnd = self.user32.GetForegroundWindow()
            if not hwnd:
                return 0, "", ""
            
            # Get Title safely
            length = self.user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                title = ""
            else:
                buff = ctypes.create_unicode_buffer(length + 2)
                self.user32.GetWindowTextW(hwnd, buff, length + 2)
                title = buff.value.strip()

            # Get Process Name
            proc_name = ""
            pid = ctypes.c_ulong()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            
            if HAS_WIN32 and pid.value:
                try:
                    proc = psutil.Process(pid.value)
                    proc_name = proc.name().lower()
                except Exception:
                    pass
            
            if not proc_name and pid.value:
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                h_proc = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if h_proc:
                    buf = ctypes.create_unicode_buffer(260)
                    size = ctypes.c_ulong(260)
                    if hasattr(ctypes.windll.psapi, 'GetProcessImageFileNameW'):
                        if ctypes.windll.psapi.GetProcessImageFileNameW(h_proc, buf, size):
                            proc_name = buf.value.split('\\')[-1].lower()
                    self.kernel32.CloseHandle(h_proc)

            return hwnd, title, proc_name
        except Exception as e:
            print(f"[WindowTracker] Foreground inspection error: {e}")
            return 0, "", ""

    def clean_browser_title(self, title_lower):
        """
        Strips browser brand suffixes, profile names, em-dashes, and zero-width spaces
        so we inspect the true document/site title.
        """
        clean = title_lower.strip()
        # Remove invisible zero-width spaces that Microsoft Edge sometimes inserts
        clean = clean.replace("\u200b", "").replace("\ufeff", "")

        # Regex patterns to strip standard browser trailing titles
        # e.g. " - Google Chrome", " — Mozilla Firefox", " - Personal - Microsoft Edge"
        patterns = [
            r"[\s\-\—\–]+google\s+chrome(\s*\(.*?\))?$",
            r"[\s\-\—\–]+(personal\s*-\s*)?microsoft\s*edge(\s*\(.*?\))?$",
            r"[\s\-\—\–]+mozilla\s+firefox(\s*\(.*?\))?$",
            r"[\s\-\—\–]+brave(\s*\(.*?\))?$",
            r"[\s\-\—\–]+opera(\s*\(.*?\))?$",
            r"[\s\-\—\–]+vivaldi(\s*\(.*?\))?$",
            r"[\s\-\—\–]+arc(\s*\(.*?\))?$"
        ]
        for pat in patterns:
            clean = re.sub(pat, "", clean, flags=re.IGNORECASE).strip()
        return clean

    def evaluate_focus(self):
        """
        Evaluates current focused window against whitelist and blacklist.
        Returns a dict:
        {
            "status": "allowed" | "warning" | "violation",
            "reason": str,
            "title": str,
            "process": str,
            "matched_item": str or None,
            "grace_time_left": float or None
        }
        """
        hwnd, title, proc_name = self.get_foreground_window_info()
        title_lower = title.lower()
        proc_lower = proc_name.lower()
        clean_title = self.clean_browser_title(title_lower)

        # 1. Desktop / Windows Explorer / System Tray / Lockscreen
        system_procs = [p.lower() for p in self.config.get("system_whitelisted_processes", [])]
        if proc_lower in system_procs:
            self.grace_start_time = None
            return {
                "status": "allowed",
                "reason": "Windows System / Shell",
                "title": title or proc_name,
                "process": proc_name,
                "matched_item": "System",
                "grace_time_left": None
            }

        # 2. Focuzzer Overlay itself
        if "focuzzer" in title_lower or "focusguard" in title_lower or "focus guard" in title_lower or proc_lower in ["focus_guard.py", "pythonw.exe", "python.exe"]:
            if "focuzzer" in title_lower or "focusguard" in title_lower or "focus guard" in title_lower:
                self.grace_start_time = None
                return {
                    "status": "allowed",
                    "reason": "Focuzzer Overlay",
                    "title": title,
                    "process": proc_name,
                    "matched_item": "Focuzzer",
                    "grace_time_left": None
                }

        # 3. Whitelisted Study Sites & Custom Whitelisted URLs FIRST!
        # User whitelist ALWAYS overrides blacklist!
        allowed_sites = [s.lower() for s in self.config.get("allowed_site_keywords", [])]
        allowed_apps = [a.lower() for a in self.config.get("allowed_app_keywords", [])]

        # Check if browser tab or window title matches ANY whitelisted site/URL
        for site in allowed_sites:
            if site in clean_title or site in title_lower or site in proc_lower:
                self.grace_start_time = None
                return {
                    "status": "allowed",
                    "reason": f"Whitelisted Site: {site.title()}",
                    "title": title,
                    "process": proc_name,
                    "matched_item": site.title(),
                    "grace_time_left": None
                }

        # Check if desktop application matches allowed study tools (VS Code, Obsidian, Notion, etc.)
        for app in allowed_apps:
            if app in proc_lower or app in clean_title or app in title_lower:
                self.grace_start_time = None
                return {
                    "status": "allowed",
                    "reason": f"Allowed Tool: {app}",
                    "title": title or proc_name,
                    "process": proc_name,
                    "matched_item": app,
                    "grace_time_left": None
                }

        # 4. Explicit Instant Blacklist (YouTube, Netflix, Reddit, Instagram, etc. - unless whitelisted)
        for blacklisted in self.config.get("instant_alarm_keywords", []):
            b_lower = blacklisted.lower()
            if b_lower in clean_title or b_lower in title_lower or b_lower in proc_lower:
                self.grace_start_time = None
                return {
                    "status": "violation",
                    "reason": f"Distraction Site/App: '{blacklisted}'",
                    "title": title or blacklisted,
                    "process": proc_name,
                    "matched_item": blacklisted,
                    "grace_time_left": 0
                }

        # 5. Web Browser Windows
        browser_processes = [b.lower() for b in self.config.get("browser_processes", [])]
        is_browser = proc_lower in browser_processes or any(b in title_lower for b in ["chrome", "edge", "firefox", "brave", "opera", "vivaldi"])

        if is_browser:
            # Check for neutral / navigation states ("New Tab", "about:blank")
            neutral_exact = ["new tab", "about:blank", "blank page", "start page", "speed dial", ""]
            is_neutral = (clean_title in neutral_exact) or clean_title.startswith("new tab")

            if is_neutral:
                grace_limit = float(self.config.get("new_tab_grace_seconds", 6.0))
                if self.grace_start_time is None:
                    self.grace_start_time = time.time()
                
                elapsed_grace = time.time() - self.grace_start_time
                remaining_grace = max(0.0, grace_limit - elapsed_grace)

                if remaining_grace > 0:
                    return {
                        "status": "warning",
                        "reason": f"New tab grace period ({int(remaining_grace)}s remaining to open allowed site)",
                        "title": title or "New Tab",
                        "process": proc_name,
                        "matched_item": "New Tab",
                        "grace_time_left": remaining_grace
                    }
                else:
                    return {
                        "status": "violation",
                        "reason": "Grace period expired! Navigate to whitelisted site.",
                        "title": title or "New Tab Timeout",
                        "process": proc_name,
                        "matched_item": "New Tab Timeout",
                        "grace_time_left": 0
                    }
            
            # Active browser tab is on an unauthorized website!
            self.grace_start_time = None
            return {
                "status": "violation",
                "reason": f"Unauthorized Site: '{clean_title or title}' (Not in Whitelist)",
                "title": title or clean_title,
                "process": proc_name,
                "matched_item": "Unauthorized Site",
                "grace_time_left": 0
            }

        # 6. Any other unauthorized non-browser desktop app (e.g. Steam, Games) -> VIOLATION!
        self.grace_start_time = None
        return {
            "status": "violation",
            "reason": f"Unauthorized App: '{title or proc_name}'",
            "title": title or proc_name,
            "process": proc_name,
            "matched_item": proc_name or title,
            "grace_time_left": 0
        }

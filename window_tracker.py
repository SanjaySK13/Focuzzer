import time
import ctypes
import re
import os
import subprocess

try:
    import win32gui
    import win32process
    import psutil
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

# PowerShell one-liner: reads address bar URL from any Chromium/Firefox window via UIAutomation
_PS_GET_URL = (
    "Add-Type -AssemblyName UIAutomationClient; "
    "$h = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]{hwnd}); "
    "if ($h -eq $null) {{ exit }}; "
    "$cond = [System.Windows.Automation.PropertyCondition]::new("
    "  [System.Windows.Automation.AutomationElement]::ControlTypeProperty, "
    "  [System.Windows.Automation.ControlType]::Edit); "
    "$el = $h.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond); "
    "if ($el -ne $null) {{ "
    "  $vp = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); "
    "  Write-Output $vp.Current.Value }}"
)

def _get_browser_url(hwnd):
    """
    Uses PowerShell + UIAutomation to read the address bar of a Chromium/Firefox window.
    Returns URL string (lowercase) or '' on failure. Runs in <100ms typically.
    """
    try:
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               _PS_GET_URL.format(hwnd=hwnd)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1.5,
                                creationflags=0x08000000)  # CREATE_NO_WINDOW
        url = result.stdout.strip().lower()
        return url
    except Exception:
        return ""


class WindowTracker:
    def __init__(self, config):
        self.config = config
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.grace_start_time = None
        # Cache last URL to avoid calling PowerShell every 100ms on same hwnd
        self._url_cache = {}   # hwnd -> (timestamp, url)
        self._URL_CACHE_TTL = 1.5  # re-query every 1.5 seconds

    def get_foreground_window_info(self):
        """Returns (hwnd, window_title, process_name) safely."""
        try:
            hwnd = self.user32.GetForegroundWindow()
            if not hwnd:
                return 0, "", ""

            length = self.user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                title = ""
            else:
                buff = ctypes.create_unicode_buffer(length + 2)
                self.user32.GetWindowTextW(hwnd, buff, length + 2)
                title = buff.value.strip()

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
            print(f"[WindowTracker] Foreground error: {e}")
            return 0, "", ""

    def _get_cached_url(self, hwnd):
        """Return cached URL for hwnd, re-fetching if TTL expired."""
        now = time.time()
        cached = self._url_cache.get(hwnd)
        if cached and (now - cached[0]) < self._URL_CACHE_TTL:
            return cached[1]
        url = _get_browser_url(hwnd)
        self._url_cache[hwnd] = (now, url)
        return url

    def clean_browser_title(self, title_lower):
        clean = title_lower.strip()
        clean = clean.replace("\u200b", "").replace("\ufeff", "")
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

    def _matches_whitelist(self, text, allowed_sites):
        """Check if any allowed site keyword appears in text."""
        for site in allowed_sites:
            if site and site in text:
                return site
        return None

    def evaluate_focus(self):
        hwnd, title, proc_name = self.get_foreground_window_info()
        title_lower = title.lower()
        proc_lower = proc_name.lower()
        clean_title = self.clean_browser_title(title_lower)

        # 1. System processes
        system_procs = [p.lower() for p in self.config.get("system_whitelisted_processes", [])]
        if proc_lower in system_procs:
            self.grace_start_time = None
            return {"status": "allowed", "reason": "Windows System / Shell",
                    "title": title or proc_name, "process": proc_name,
                    "matched_item": "System", "grace_time_left": None}

        # 2. Focuzzer itself
        if "focuzzer" in title_lower or "focusguard" in title_lower or "focus guard" in title_lower:
            self.grace_start_time = None
            return {"status": "allowed", "reason": "Focuzzer Overlay",
                    "title": title, "process": proc_name,
                    "matched_item": "Focuzzer", "grace_time_left": None}

        allowed_sites = [s.lower().strip() for s in self.config.get("allowed_site_keywords", []) if s.strip()]
        allowed_apps  = [a.lower().strip() for a in self.config.get("allowed_app_keywords", []) if a.strip()]

        # 3. Browser detection
        browser_processes = [b.lower() for b in self.config.get("browser_processes", [])]
        is_browser = (proc_lower in browser_processes or
                      any(b in title_lower for b in ["chrome", "edge", "firefox", "brave", "opera", "vivaldi"]))

        # --- URL-based whitelist check (the KEY fix for Spotify/dynamic titles) ---
        if is_browser and hwnd:
            real_url = self._get_cached_url(hwnd)
            if real_url:
                matched = self._matches_whitelist(real_url, allowed_sites)
                if matched:
                    self.grace_start_time = None
                    return {"status": "allowed", "reason": f"Whitelisted URL: {matched.title()}",
                            "title": title, "process": proc_name,
                            "matched_item": matched.title(), "grace_time_left": None}

        # 4. Title/process keyword whitelist
        for site in allowed_sites:
            if site in clean_title or site in title_lower or site in proc_lower:
                self.grace_start_time = None
                return {"status": "allowed", "reason": f"Whitelisted: {site.title()}",
                        "title": title, "process": proc_name,
                        "matched_item": site.title(), "grace_time_left": None}

        for app in allowed_apps:
            if app in proc_lower or app in clean_title or app in title_lower:
                self.grace_start_time = None
                return {"status": "allowed", "reason": f"Allowed Tool: {app}",
                        "title": title or proc_name, "process": proc_name,
                        "matched_item": app, "grace_time_left": None}

        # 5. Instant blacklist (only if URL didn't whitelist)
        for blacklisted in self.config.get("instant_alarm_keywords", []):
            b_lower = blacklisted.lower()
            if b_lower in clean_title or b_lower in title_lower or b_lower in proc_lower:
                self.grace_start_time = None
                return {"status": "violation", "reason": f"Distraction: '{blacklisted}'",
                        "title": title or blacklisted, "process": proc_name,
                        "matched_item": blacklisted, "grace_time_left": 0}

        # 6. Browser with unrecognized tab
        if is_browser:
            neutral_exact = ["new tab", "about:blank", "blank page", "start page", "speed dial", ""]
            is_neutral = (clean_title in neutral_exact) or clean_title.startswith("new tab")

            if is_neutral:
                grace_limit = float(self.config.get("new_tab_grace_seconds", 6.0))
                if self.grace_start_time is None:
                    self.grace_start_time = time.time()
                elapsed_grace = time.time() - self.grace_start_time
                remaining_grace = max(0.0, grace_limit - elapsed_grace)
                if remaining_grace > 0:
                    return {"status": "warning",
                            "reason": f"New tab – navigate to an allowed site ({int(remaining_grace)}s)",
                            "title": title or "New Tab", "process": proc_name,
                            "matched_item": "New Tab", "grace_time_left": remaining_grace}
                else:
                    return {"status": "violation", "reason": "Grace period expired! Open an allowed site.",
                            "title": title or "New Tab Timeout", "process": proc_name,
                            "matched_item": "New Tab Timeout", "grace_time_left": 0}

            self.grace_start_time = None
            return {"status": "violation",
                    "reason": f"Unauthorized Site: '{clean_title or title}' (Not in Whitelist)",
                    "title": title or clean_title, "process": proc_name,
                    "matched_item": "Unauthorized Site", "grace_time_left": 0}

        # 7. Unknown desktop app → violation
        self.grace_start_time = None
        return {"status": "violation",
                "reason": f"Unauthorized App: '{title or proc_name}'",
                "title": title or proc_name, "process": proc_name,
                "matched_item": proc_name or title, "grace_time_left": 0}

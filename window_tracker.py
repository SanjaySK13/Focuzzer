import time
from concurrent.futures import ThreadPoolExecutor
import ctypes
import os
import re
import sys
from urllib.parse import urlsplit
import subprocess

from config import GOOGLE_MEET_HOST

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
    "$edits = $h.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond); "
    "foreach ($el in $edits) {{ "
    "  if ($el.Current.AutomationId -notin @('urlbar-input','addressEditBox','omnibox') "
    "      -and $el.Current.Name -notmatch 'address (and search )?bar|enter (an? )?address|type (an? )?url') {{ continue }}; "
    "  $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker; "
    "  $parent = $walker.GetParent($el); $isPage = $false; "
    "  while ($parent -and -not $parent.Equals($h)) {{ "
    "    if ($parent.Current.ControlType -eq [System.Windows.Automation.ControlType]::Document) "
    "      {{ $isPage = $true; break }}; "
    "    $parent = $walker.GetParent($parent) }}; "
    "  if ($isPage) {{ continue }}; "
    "  $value = $null; "
    "  if ($el.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$value)) {{ "
    "    Write-Output $value.Current.Value; break }} }}"
)

def _get_browser_url(hwnd):
    """
    Uses PowerShell + UIAutomation to read the address bar of a Chromium/Firefox window.
    Returns the address bar value (lowercase) or '' on failure.
    """
    try:
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               _PS_GET_URL.format(hwnd=hwnd)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0,
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
        self.user32.GetForegroundWindow.restype = ctypes.c_void_p
        self.user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        self.user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        self.user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        self.kernel32.OpenProcess.restype = ctypes.c_void_p
        self.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.grace_start_time = None
        self._url_worker = ThreadPoolExecutor(max_workers=1)
        self._url_lookup = None
        self._url_lookup_key = None
        self._url_cache = {}

    def reset_session(self):
        self.grace_start_time = None
        self._url_cache.clear()
        self._url_lookup_key = None

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
                    try:
                        buf = ctypes.create_unicode_buffer(260)
                        size = ctypes.c_ulong(len(buf))
                        if self.kernel32.QueryFullProcessImageNameW(
                                ctypes.c_void_p(h_proc), 0, buf, ctypes.byref(size)):
                            proc_name = buf.value.split('\\')[-1].lower()
                    finally:
                        self.kernel32.CloseHandle(h_proc)

            return hwnd, title, proc_name
        except Exception as e:
            print(f"[WindowTracker] Foreground error: {e}")
            return 0, "", ""

    def _get_cached_url(self, hwnd, title):
        """Return the last completed reading, or None while the first read is pending."""
        now = time.monotonic()
        key = (hwnd, title)
        if self._url_lookup is not None and self._url_lookup.done():
            if self._url_lookup_key == key:
                self._url_cache[hwnd] = (now, title, self._url_lookup.result())
            self._url_lookup = None
            self._url_lookup_key = None

        cached = self._url_cache.get(hwnd)
        if cached is not None and (cached[1] != title or now - cached[0] > 5.0):
            self._url_cache.pop(hwnd)
            cached = None
        if self._url_lookup is None and (cached is None or now - cached[0] >= 1.5):
            self._url_lookup = self._url_worker.submit(_get_browser_url, hwnd)
            self._url_lookup_key = key
        return cached[2] if cached is not None else None

    def close(self):
        self._url_worker.shutdown(wait=False, cancel_futures=True)

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

    @staticmethod
    def _matches_whitelist(text, allowed_sites):
        """Match whole keywords, including names made up of multiple words."""
        for site in allowed_sites:
            if re.search(rf"(?<!\w){re.escape(site)}(?!\w)", text):
                return site
        return None

    @staticmethod
    def _browser_host(url):
        try:
            host = urlsplit(url if "://" in url else f"//{url}").hostname or ""
            if "." in host and not any(char.isspace() for char in host):
                return host.rstrip(".")
        except ValueError:
            pass
        return ""

    def evaluate_focus(self):
        hwnd, title, proc_name = self.get_foreground_window_info()
        title_lower = title.lower()
        proc_lower = proc_name.lower()
        clean_title = self.clean_browser_title(title_lower)

        # 1. System processes
        system_procs = {p.lower() for p in self.config.get("system_whitelisted_processes", [])}
        if not hwnd or not proc_lower:
            return {"status": "neutral", "reason": "Foreground window unavailable",
                    "title": title, "process": proc_name,
                    "matched_item": "System", "grace_time_left": None}
        if proc_lower in system_procs:
            self.grace_start_time = None
            return {"status": "allowed", "reason": "Windows System / Shell",
                    "title": title or proc_name, "process": proc_name,
                    "matched_item": "System", "grace_time_left": None}

        # 2. Focuzzer itself
        own_process = proc_lower == os.path.basename(sys.executable).lower()
        if own_process and title_lower.startswith(("focuzzer", "focusguard", "focus guard")):
            return {"status": "neutral", "reason": "Focuzzer Overlay",
                    "title": title, "process": proc_name,
                    "matched_item": "Focuzzer", "grace_time_left": None}

        allowed_sites = [s.lower().strip() for s in self.config.get("allowed_site_keywords", []) if s.strip()]
        allowed_apps  = [a.lower().strip() for a in self.config.get("allowed_app_keywords", []) if a.strip()]

        # 3. Browser detection
        browser_processes = [b.lower() for b in self.config.get("browser_processes", [])]
        is_browser = proc_lower in browser_processes

        # --- URL-based whitelist check (the KEY fix for Spotify/dynamic titles) ---
        url = self._get_cached_url(hwnd, title) if is_browser else ""
        host = self._browser_host(url) if url else ""
        if host:
            matched = next((site for site in allowed_sites
                            if (host == site or host.endswith(f".{site}"))
                            or ("." not in site and site in host.split("."))), None)
        elif is_browser:
            matched = self._matches_whitelist(clean_title, allowed_sites)
            if GOOGLE_MEET_HOST in allowed_sites and re.fullmatch(
                    r"(?:google meet|meet)(?:\s*[-\u2013\u2014]\s*[a-z]{3}-[a-z]{4}-[a-z]{3})?",
                    clean_title):
                matched = "Google Meet"
            if url is None and not matched:
                return {"status": "checking", "reason": "Checking browser address",
                        "title": title, "process": proc_name,
                        "matched_item": None, "grace_time_left": None}
        else:
            matched = self._matches_whitelist(proc_lower, allowed_sites)
        if matched:
            self.grace_start_time = None
            return {"status": "allowed", "reason": f"Whitelisted: {matched.title()}",
                    "title": title, "process": proc_name,
                    "matched_item": matched.title(), "grace_time_left": None}

        if not is_browser:
            app = self._matches_whitelist(proc_lower, allowed_apps)
            if app:
                self.grace_start_time = None
                return {"status": "allowed", "reason": f"Allowed Tool: {app}",
                        "title": title or proc_name, "process": proc_name,
                        "matched_item": app, "grace_time_left": None}

        # 5. Instant blacklist (only if URL didn't whitelist)
        distraction_sources = (clean_title, proc_lower, host) if is_browser else (proc_lower,)
        for blacklisted in self.config.get("instant_alarm_keywords", []):
            b_lower = blacklisted.lower()
            if b_lower and any(b_lower in value for value in distraction_sources):
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
            if not host:
                return {"status": "unverified", "reason": "Browser address unavailable",
                        "title": title, "process": proc_name,
                        "matched_item": None, "grace_time_left": None}
            return {"status": "violation",
                    "reason": f"Unauthorized Site: '{clean_title or title}' (Not in Whitelist)",
                    "title": title or clean_title, "process": proc_name,
                    "matched_item": "Unauthorized Site", "grace_time_left": 0}

        # 7. Ordinary desktop software is allowed by default.
        self.grace_start_time = None
        return {"status": "allowed", "reason": "Desktop App",
                "title": title or proc_name, "process": proc_name,
                "matched_item": "Desktop App", "grace_time_left": None}

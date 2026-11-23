from copy import deepcopy
import json
import os
import re
import sys

DEFAULT_CONFIG = {
    "appearance": "basic",
    "session_allowlist_version": 1,
    # Core sites allowed (user's explicit focus domains)
    "allowed_site_keywords": [
        "notebooklm",
        "notebook lm",
        "gemini",
        "whatsapp"
    ],
    # Local desktop study apps allowed by default (notes, code, pdfs)
    "allowed_app_keywords": [
        "focuzzer",
        "focusguard",
        "visual studio code",
        "code",
        "cursor",
        "sublime_text",
        "notepad",
        "notepad++",
        "obsidian",
        "notion",
        "onenote",
        "acrobat",
        "sumatrapdf",
        "foxitreader",
        "pdf",
        "calculator",
        "anki"
    ],
    # Windows internal system processes (MUST be allowed so Start menu / Alt+Tab / Screenshots don't trigger false alarms)
    "system_whitelisted_processes": [
        "explorer.exe",
        "shellexperiencehost.exe",
        "shellhost.exe",
        "systemsettingsbroker.exe",
        "windowsterminal.exe",
        "openconsole.exe",
        "conhost.exe",
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "startmenuexperiencehost.exe",
        "searchhost.exe",
        "searchapp.exe",
        "lockapp.exe",
        "taskmgr.exe",
        "systemsettings.exe",
        "applicationframehost.exe",
        "snippingtool.exe",
        "screenclippinghost.exe",
        "dwm.exe",
        "ctfmon.exe",
        "smartscreen.exe"
    ],
    # Explicit instant-trigger distraction keywords (0 grace period)
    "instant_alarm_keywords": [
        "youtube",
        "netflix",
        "reddit",
        "twitter",
        "x.com",
        "instagram",
        "facebook",
        "tiktok",
        "twitch",
        "discord",
        "steam",
        "spotify",
        "anime",
        "prime video",
        "hulu",
        "disney",
        "roblox",
        "pinterest",
        "telegram",
        "9gag",
        "crunchyroll",
        "hotstar",
        "kick.com"
    ],
    # Known browser processes
    "browser_processes": [
        "chrome.exe",
        "msedge.exe",
        "brave.exe",
        "firefox.exe",
        "opera.exe",
        "vivaldi.exe",
        "arc.exe",
        "waterfox.exe"
    ],
    # Sound & Volume settings
    "blast_max_volume": True,
    "alarm_high_hz": 2800,
    "alarm_low_hz": 1800,
    "beep_duration_ms": 150,
    
    # Grace period in seconds for "New Tab" / blank pages (to allow typing an allowed URL)
    "new_tab_grace_seconds": 6.0,
    
    # Hourly check-in settings
    "hourly_checkin_interval_minutes": 60,
    "hourly_checkin_timeout_seconds": 60,
    
    # Anti-cheat / Lock settings
    "emergency_exit_phrase": "I AM BREAKING MY STUDY PROMISE",
    
    # Saved custom input from UI (remembered across restarts)
    "custom_extra_input": ""
}

# A one-file build extracts Python modules to a temporary directory on every run.
# Keep the portable app's data alongside the executable so it survives restarts.
DATA_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
HISTORY_FILE = os.path.join(DATA_DIR, "study_history.json")

GOOGLE_MEET_HOST = "meet.google.com"
GOOGLE_MEET_HOSTS = {GOOGLE_MEET_HOST, "gmeet.com"}

def parse_and_expand_keywords(raw_text):
    """
    Parses user-entered URLs, domains, or keywords and extracts all matching variants.
    e.g. 'discord.com' -> ['discord', 'discord.com']
    e.g. 'https://leetcode.com/problemset' -> ['leetcode', 'leetcode.com', 'https://leetcode.com/problemset']
    """
    if not raw_text:
        return []
    
    items = [x.strip() for x in raw_text.split(',') if x.strip()]
    expanded = set()
    
    for item in items:
        s = item.lower()
        expanded.add(s)
        
        # Strip protocol
        clean = re.sub(r'^https?:\/\/', '', s)
        # Strip path and queries
        host = clean.split('/')[0].split('?')[0].split('#')[0].strip()
        
        if host:
            expanded.add(host)
            # Remove port if any
            host_no_port = host.split(':')[0]
            expanded.add(host_no_port)
            
            # Remove www.
            if host_no_port.startswith('www.'):
                host_no_port = host_no_port[4:]
                expanded.add(host_no_port)

            if host_no_port.rstrip(".") in GOOGLE_MEET_HOSTS:
                expanded.add(GOOGLE_MEET_HOST)
                continue
                
            # Split domain parts
            parts = host_no_port.split('.')
            common_tlds = {'com', 'org', 'net', 'edu', 'gov', 'io', 'ai', 'app', 'dev', 'co', 'in', 'uk', 'ca', 'de', 'me', 'xyz', 'cc'}
            while len(parts) > 1 and parts[-1] in common_tlds:
                parts.pop()
            if len(parts[-1]) >= 3:
                expanded.add(parts[-1])
                    
    return sorted(list(expanded))

def apply_custom_whitelisted_urls(config, raw_text):
    """Remember the setup input and build the allowlist for this session."""
    config["custom_extra_input"] = raw_text.strip()
    return {
        **config,
        "allowed_site_keywords": list(dict.fromkeys([
            *config["allowed_site_keywords"], *parse_and_expand_keywords(raw_text)
        ])),
    }

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                config = deepcopy(DEFAULT_CONFIG)
                config.update(data)
                config["system_whitelisted_processes"] = list(dict.fromkeys([
                    *DEFAULT_CONFIG["system_whitelisted_processes"],
                    *config["system_whitelisted_processes"],
                ]))
                if not data.get("session_allowlist_version"):
                    # Older saves mixed past session entries into these two lists.
                    config["allowed_site_keywords"] = list(DEFAULT_CONFIG["allowed_site_keywords"])
                    config["instant_alarm_keywords"] = list(DEFAULT_CONFIG["instant_alarm_keywords"])
                config["session_allowlist_version"] = 1
                return config
        except Exception:
            pass
    return deepcopy(DEFAULT_CONFIG)

def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"[Config] Failed to save config: {e}")

def append_study_history(session_record):
    """Logs completed or overridden study sessions."""
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    
    history.append(session_record)
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=4)
    except Exception as e:
        print(f"[History] Failed to log study session: {e}")

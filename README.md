# 🛡️ Focuzzer: Hardcore Anti-Distraction Study Sentinel

> **Built for extreme digital addiction & zero-distraction study lock-in.**

---

## ⚡ Quick Start (How to Run)

Navigate to the `focusguard` folder:
`C:\Users\sanja\.gemini\antigravity\scratch\focusguard`

1. **Option A (Standard Launcher):**
   - Double-click **`run_focuzzer.bat`** (or **`run_focus_guard.bat`**)
2. **Option B (Silent Background Launcher - No Terminal):**
   - Double-click **`run_silent.vbs`**

---

## 🔒 How It Works

### 1. The Whitelist Barrier & Custom URL Support
- **Default Allowed Sites:**
  - **NotebookLM** (`notebooklm.google.com`)
  - **Gemini** (`gemini.google.com`)
  - **WhatsApp** (`web.whatsapp.com` or desktop app)
  - *Plus local study tools:* VS Code, Obsidian, Notion, PDF Readers, Notepad, Anki.
- **Whitelist ANY Custom Site or URL:**
  - Type or paste any website or URL in the setup field (e.g. `discord.com`, `https://discord.com`, `leetcode.com`, `claude.ai`, `chatgpt.com`).
  - **Smart Expansion:** Typing `discord.com` automatically extracts and whitelists both the domain (`discord.com`) and the keyword (`discord`), covering both the browser tab and the desktop app (`Discord.exe`).
  - **Priority Override:** Explicitly whitelisted sites override the default blacklist!
  - **Remembered Across Restarts:** Saved in `config.json` so your custom sites stay saved.
- **Forbidden Sites & Apps:**
  - YouTube, Reddit, Instagram, Twitter/X, TikTok, Twitch, Netflix, Steam, games, or any unauthorized site (unless you whitelist them).
  - **Action on Violation:**
    1. Cranks Windows master volume up to **100%**.
    2. Blasts a piercing alternating dual-tone siren (`2800 Hz` & `1800 Hz`).
    3. Flashes a prominent red alert banner directly on top of your screen:
       `🚨 DISTRACTION DETECTED: [Site Name]! GET BACK TO STUDYING!`
    4. The siren stops **immediately** the moment you click back into NotebookLM, Gemini, or WhatsApp!

### 2. The Strict Session Lock & Jumbled Quitting Challenge
- At the start of your session, you choose your commitment duration (e.g. 30m, 45m, 1h, 2h, 3h, or custom).
- Once you click **"START HARDCORE STUDY SESSION"**:
  - The **Switch Off button is completely LOCKED and DISABLED**.
  - Closing via `[X]` or `Alt+F4` is intercepted.
  - The HUD displays a real-time countdown: `🔒 Switch-off unlocks in: HH:MM:SS`.
  - **Only when your target duration finishes** does the switch-off button dynamically unlock, turn glowing green, and allow you to end the session!
- **Quitting Verification Challenge:**
  - If you attempt to quit early or override the session, you **MUST manually type a 26-character randomized jumbled line of characters, numbers, and symbols** (e.g., `G&WCHY6nL2QRfxKb#5VGg!TmLF`).
  - **Anti-Cheat Enforcement:** Copy & Paste (`Ctrl+V`, `Shift+Insert`, right-click) is **COMPLETELY DISABLED** on the input box. You must type every character one-by-one, forcing your brain to pause and snap out of impulse quitting!

### 3. Verification Prompts: Hourly & Random Midpoint Checker
- **Random Midpoint Focus Checker (Halfway ± 10s):**
  - Triggers randomly within `± 10 seconds` of your session's exact midpoint (e.g. at 14m 52s for a 30m session, or 29m 55s for a 1-hour session).
  - A small, compact card pops up requiring you to press **Enter**, **Space**, or click `[✓ YES, STILL STUDYING!]` within 25 seconds before the siren blasts.
- **Hourly Check-In Prompts:**
  - Every **60 minutes**, an engagement modal verifies you haven't abandoned your desk or fallen asleep.

### 4. Episode-Based Distraction Tracking & Instant Audio Trigger
- **Accurate Counting:** Counts distraction **episodes/events** rather than loop clock ticks. Switching to YouTube and staying there for 20 seconds counts as **1 distraction**, not 40.
- **Instant Audio On/Off:** Polling runs at 100ms and audio operates on micro 80ms slices. The alarm fires immediately when leaving allowed tabs and cuts off immediately when returning.

### 4. Floating On-Screen HUD Overlay
- A sleek, draggable floating HUD stays anchored on top of your screen:
  - ⏱️ **Elapsed Study Time** (`01:23:45`)
  - ⏳ **Time Until Unlock** (`Locked: 00:36:15`)
  - 🟢 **Focus Status** (`🟢 Focused: NotebookLM`)
  - 🚨 **Distraction Warning** (Turns flashing red if distracted)

### 5. Emergency Override Safeguard
If you face a genuine computer emergency before your session ends, click the `⚠️` icon on the HUD. To unlock early, you are required to type the anti-cheat pledge:
`"I AM BREAKING MY STUDY PROMISE"`
This psychological barrier prevents impulsive tab-switching while guaranteeing you are never locked out of your PC.

---

## 🛠️ Configuration (`config.json`)
You can tweak settings anytime in `config.json`:
- `blast_max_volume`: Force 100% volume on alarm (`true`/`false`)
- `new_tab_grace_seconds`: Grace period when opening a new tab before navigating (`6.0`s)
- `hourly_checkin_interval_minutes`: Check-in frequency (`60` mins)
- `allowed_site_keywords`: Additional whitelisted keywords

# Focuzzer

A lightweight Windows focus timer and distraction blocker built with Rust and Tauri. Set a study goal, pick your allowed or blocked apps and websites, and stay locked in until the timer finishes.

## Download

Download the latest `focuzzer-rusted.exe` from the [Releases](https://github.com/SanjaySK13/Focuzzer/releases) page and run it directly. No installation or terminal required.

## Features

- **Distraction Blocking:** Monitors the active window and browser address bar. Opening a blocked app or website triggers a full-volume alarm and on-screen alert until you return to your work.
- **Allowlist & Blocklist Modes:** Choose from preset study tools and websites or add your own custom domains and apps.
- **Floating Timer Pill:** An always-on-top compact pill with two styles—Countdown and Color Fill. Click it when a session ends to view your stats.
- **Impulse-Proof Early Quit:** Ending a session early requires manually typing a randomized quit code.
- **Study Check-Ins & History:** Periodic halfway check-ins keep you on track, and completed sessions are saved with timestamps.

## Build from Source

Requires the Rust MSVC toolchain, Visual Studio Build Tools (C++ workload), and Microsoft Edge WebView2 Runtime:

```powershell
cargo +stable-x86_64-pc-windows-msvc run --locked --manifest-path src-tauri/Cargo.toml
```

---

*The original Python/Tkinter version is preserved in the [`legacy-python`](https://github.com/SanjaySK13/Focuzzer/tree/legacy-python) branch.*

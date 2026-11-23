# Focuzzer Rusted

Windows-first Tauri prototype. The Rust process owns the monotonic timer and writes session history to its own app-data directory. The frontend uses one visual theme and offers two presentations for the floating timer.

## Run on Windows

Install the Rust MSVC toolchain, Visual Studio Build Tools with the Desktop development with C++ workload, and Microsoft Edge WebView2 Runtime. From this directory run:

```powershell
cargo +stable-x86_64-pc-windows-msvc run --locked --manifest-path src-tauri/Cargo.toml
```

Set a goal and duration, choose **Countdown** or **Color fill**, then start. Hover the pill for details, click its top row to keep it expanded, drag the top row to move it, or press Escape to collapse it. To leave early, type the random code shown by **End early**. The Windows binary can be opened directly without a terminal.

To preview the frontend without Tauri, open `ui/index.html` directly or serve the `ui` folder over HTTP:

```powershell
python -m http.server 4173 --bind 127.0.0.1 --directory ui
```

Open http://127.0.0.1:4173. In browser preview mode, the floating timer stays inside the page and history uses browser storage.

## Rewrite scope

The interface audio comes from [Kenney Interface Sounds](https://kenney.nl/assets/interface-sounds), licensed CC0. The selected clips and license are bundled in `ui/sounds`.

Windows focus enforcement reads supported browsers' address bars directly through UI Automation. Confirmed sites outside the allowlist trigger a banner and an alternating alarm tone at full device volume. Focuzzer restores the previous volume and mute setting when the alarm stops. A browser address that Windows cannot verify does not trigger the alarm. Session history records distraction episodes and supports deleting individual entries. Migration from the Python app remains to be ported.

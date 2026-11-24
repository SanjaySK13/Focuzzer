use crate::quit;
#[path = "alarm_volume.rs"]
mod alarm_volume;
#[path = "focus.rs"]
mod focus;
use serde::{Deserialize, Serialize};

use std::{
    fs,
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Instant, SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, State, WebviewWindow};

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct Plan {
    minutes: u32,
    goal: String,
    style: String,
    sound: bool,
    #[serde(default)]
    sites: String,
    #[serde(default)]
    blocked_sites: String,
    #[serde(default)]
    blocklist_mode: bool,
    #[serde(default = "default_unreadable_warning")]
    warn_unreadable_browser: bool,
    #[serde(default)]
    allowed_apps: String,
}

fn default_unreadable_warning() -> bool {
    true
}

struct Running {
    plan: Plan,
    started: Instant,
    rules: Vec<String>,
    blocked_rules: Vec<String>,
    allowed_apps: Vec<String>,
    distractions: u32,
    in_distraction: bool,
    blocked_site: Option<String>,
    active_tab: Option<String>,
    new_tab_since: Option<Instant>,
    unreadable_since: Option<Instant>,
    check_in: CheckIn,
    quit_code: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Snapshot {
    plan: Plan,
    elapsed_seconds: f64,
    distractions: u32,
    blocked_site: Option<String>,
    active_tab: Option<String>,
}

enum CheckIn {
    Waiting,
    Prompted(Instant),
    Confirmed,
}

const CHECK_IN_GRACE: std::time::Duration = std::time::Duration::from_secs(10);

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct Record {
    #[serde(default)]
    id: String,
    goal: String,
    minutes: u32,
    elapsed_seconds: u32,
    completed: bool,
    #[serde(default)]
    distractions: u32,
    #[serde(default)]
    completed_at: u64,
}

#[derive(Default)]
struct Session {
    running: Mutex<Option<Running>>,
    history_write: Mutex<()>,
    alarm: Arc<AtomicBool>,
    stopping: Arc<AtomicBool>,
    audio: Mutex<Option<std::thread::JoinHandle<()>>>,
    mute_exit_sound: AtomicBool,
}

#[tauri::command]
fn begin(plan: Plan, session: State<Session>) -> Result<(), String> {
    if !(1..=180).contains(&plan.minutes)
        || !matches!(plan.style.as_str(), "digits" | "fill")
        || plan.goal.chars().count() > 100
        || plan.sites.len() > 2000
        || plan.blocked_sites.len() > 2000
        || plan.allowed_apps.len() > 2000
    {
        return Err("Check the session settings and try again.".into());
    }
    let rules = focus::website_rules(&plan.sites)?;
    let blocked_rules = focus::website_rules(&plan.blocked_sites)?;
    let mut state = session.running.lock().map_err(|err| err.to_string())?;
    if state.is_some() {
        return Err("A session is already running.".into());
    }
    *state = Some(Running {
        allowed_apps: plan
            .allowed_apps
            .split([',', '\n'])
            .map(str::trim)
            .filter(|name| !name.is_empty())
            .map(|value| focus::allowed_app_rule(value).map(|name| focus::app_name(&name)))
            .collect::<Result<_, _>>()?,
        plan,
        started: Instant::now(),
        rules,
        blocked_rules,
        distractions: 0,
        in_distraction: false,
        blocked_site: None,
        active_tab: None,
        new_tab_since: None,
        unreadable_since: None,
        check_in: CheckIn::Waiting,
        quit_code: quit::challenge()?,
    });
    Ok(())
}

#[tauri::command]
fn validate_allow_item(value: String, website: bool) -> Result<String, String> {
    if value.len() > 512 {
        return Err("This entry is too long.".into());
    }
    if website {
        focus::allowed_website_rule(&value)
    } else {
        focus::allowed_app_rule(&value)
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Reminder {
    seconds_left: u64,
    sound: bool,
}

#[tauri::command]
fn reminder(session: State<Session>) -> Result<Option<Reminder>, String> {
    let state = session.running.lock().map_err(|err| err.to_string())?;
    Ok(state.as_ref().and_then(|run| {
        if let CheckIn::Prompted(shown) = run.check_in {
            Some(Reminder {
                seconds_left: CHECK_IN_GRACE
                    .saturating_sub(shown.elapsed())
                    .as_secs_f64()
                    .ceil() as u64,
                sound: run.plan.sound,
            })
        } else {
            None
        }
    }))
}

#[tauri::command]
fn confirm_studying(app: AppHandle, session: State<Session>) -> Result<(), String> {
    {
        let mut state = session.running.lock().map_err(|err| err.to_string())?;
        let run = state.as_mut().ok_or("There is no active session.")?;
        if matches!(run.check_in, CheckIn::Prompted(_)) {
            run.check_in = CheckIn::Confirmed;
            session
                .alarm
                .store(run.blocked_site.is_some(), Ordering::Release);
        }
    }
    window(&app, "reminder")?.hide().map_err(|e| e.to_string())
}

#[tauri::command]
fn snapshot(session: State<Session>) -> Result<Option<Snapshot>, String> {
    let state = session.running.lock().map_err(|err| err.to_string())?;
    Ok(state.as_ref().map(|running| Snapshot {
        plan: running.plan.clone(),
        elapsed_seconds: running.started.elapsed().as_secs_f64(),
        distractions: running.distractions,
        blocked_site: running.blocked_site.clone(),
        active_tab: running.active_tab.clone(),
    }))
}

fn history_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    Ok(app
        .path()
        .app_local_data_dir()
        .map_err(|e| e.to_string())?
        .join("sessions.json"))
}

#[tauri::command]
fn history(app: AppHandle, session: State<Session>) -> Result<Vec<Record>, String> {
    let _write = session.history_write.lock().map_err(|e| e.to_string())?;
    load_history(&history_path(&app)?)
}

fn load_history(path: &Path) -> Result<Vec<Record>, String> {
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(error.to_string()),
    };
    let Ok(mut records) = serde_json::from_slice::<Vec<Record>>(&bytes) else {
        let mut backup = path.with_extension("bak");
        let mut suffix = 1;
        while backup.try_exists().map_err(|e| e.to_string())? {
            backup = path.with_extension(format!("{suffix}.bak"));
            suffix += 1;
        }
        fs::rename(path, backup)
            .map_err(|error| format!("Could not back up damaged session history: {error}"))?;
        return Ok(Vec::new());
    };
    let mut seen = std::collections::HashSet::new();
    let mut migrated = false;
    for record in &mut records {
        if record.id.is_empty() || !seen.insert(record.id.clone()) {
            record.id = uuid::Uuid::new_v4().to_string();
            seen.insert(record.id.clone());
            migrated = true;
        }
    }
    if migrated {
        write_history(path, &records)?;
    }
    Ok(records)
}

#[tauri::command]
fn finish(app: AppHandle, session: State<Session>, code: Option<String>) -> Result<Record, String> {
    let _write = session.history_write.lock().map_err(|e| e.to_string())?;
    let (record, quit_code) = {
        let state = session.running.lock().map_err(|err| err.to_string())?;
        let running = state.as_ref().ok_or("There is no active session.")?;
        let elapsed = running.started.elapsed().as_secs().min(u32::MAX as u64) as u32;
        let record = Record {
            id: uuid::Uuid::new_v4().to_string(),
            goal: running.plan.goal.clone(),
            minutes: running.plan.minutes,
            elapsed_seconds: elapsed,
            completed: elapsed >= running.plan.minutes * 60,
            distractions: running.distractions,
            completed_at: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs(),
        };
        (record, running.quit_code.clone())
    };
    if !record.completed
        && !code.as_deref().is_some_and(|entry| {
            entry == quit_code || (entry.len() <= 128 && quit::matches_private_command(entry))
        })
    {
        return Err("The code doesn’t match. Check capitalization and try again.".into());
    }
    let path = history_path(&app)?;
    let mut records = load_history(&path)?;
    records.push(record.clone());
    write_history(&path, &records)?;
    let mut state = session.running.lock().map_err(|err| err.to_string())?;
    *state = None;
    session.alarm.store(false, Ordering::Release);
    Ok(record)
}

#[tauri::command]
fn quit_code(session: State<Session>) -> Result<String, String> {
    let state = session.running.lock().map_err(|e| e.to_string())?;
    state
        .as_ref()
        .map(|active| active.quit_code.clone())
        .ok_or("There is no active session.".into())
}

#[tauri::command]
fn open_quit(app: AppHandle) -> Result<(), String> {
    window(&app, "alarm")?.hide().map_err(|e| e.to_string())?;
    window(&app, "reminder")?
        .hide()
        .map_err(|e| e.to_string())?;
    let dialog = window(&app, "quit")?;
    dialog.show().map_err(|e| e.to_string())?;
    dialog.set_focus().map_err(|e| e.to_string())
}

#[tauri::command]
fn close_quit(app: AppHandle) -> Result<(), String> {
    window(&app, "quit")?.hide().map_err(|e| e.to_string())
}

#[tauri::command]
fn open_repo() -> Result<(), String> {
    let windows = std::env::var_os("SystemRoot").ok_or("Windows system folder unavailable.")?;
    std::process::Command::new(std::path::PathBuf::from(windows).join("explorer.exe"))
        .arg("https://github.com/SanjaySK13/Focuzzer")
        .spawn()
        .map(|_| ())
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn set_exit_sound(session: State<Session>, enabled: bool) {
    session.mute_exit_sound.store(!enabled, Ordering::Release);
}

#[tauri::command]
fn delete_session(app: AppHandle, session: State<Session>, id: String) -> Result<(), String> {
    let _write = session.history_write.lock().map_err(|e| e.to_string())?;
    let path = history_path(&app)?;
    let mut records = load_history(&path)?;
    let index = records
        .iter()
        .position(|record| record.id == id)
        .ok_or("That session is no longer in history.")?;
    records.remove(index);
    write_history(&path, &records)
}

#[tauri::command]
fn rename_session(
    app: AppHandle,
    session: State<Session>,
    id: String,
    goal: String,
) -> Result<(), String> {
    let goal = goal.trim();
    if goal.is_empty() || goal.chars().count() > 100 {
        return Err("Enter a session name between 1 and 100 characters.".into());
    }
    let _write = session.history_write.lock().map_err(|e| e.to_string())?;
    let path = history_path(&app)?;
    let mut records = load_history(&path)?;
    let record = records
        .iter_mut()
        .find(|record| record.id == id)
        .ok_or("Session no longer exists.")?;
    record.goal = goal.to_owned();
    write_history(&path, &records)
}

fn write_history(path: &Path, records: &[Record]) -> Result<(), String> {
    fs::create_dir_all(path.parent().ok_or("Invalid history folder.")?)
        .map_err(|e| e.to_string())?;
    let temporary = path.with_extension("tmp");
    fs::write(
        &temporary,
        serde_json::to_vec(records).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    fs::rename(temporary, path).map_err(|e| e.to_string())
}

fn window(app: &AppHandle, label: &str) -> Result<WebviewWindow, String> {
    app.get_webview_window(label)
        .ok_or_else(|| format!("Missing {label} window."))
}

fn fit_to_work_area(window: &WebviewWindow) -> tauri::Result<()> {
    if window.is_minimized()? || window.is_maximized()? {
        return Ok(());
    }
    let Some(monitor) = window.current_monitor()?.or(window.primary_monitor()?) else {
        return Ok(());
    };
    let area = monitor.work_area();
    let position = window.outer_position()?;
    let size = window.outer_size()?;
    let x = position.x.clamp(
        area.position.x,
        area.position.x + area.size.width.saturating_sub(size.width) as i32,
    );
    let y = position.y.clamp(
        area.position.y,
        area.position.y + area.size.height.saturating_sub(size.height) as i32,
    );
    if (x, y) != (position.x, position.y) {
        window.set_position(tauri::PhysicalPosition::new(x, y))?;
    }
    Ok(())
}

fn resize_pill(pill: &WebviewWindow, amount: f64, keep_center: bool) -> Result<(), String> {
    let amount = amount.clamp(0.0, 1.0);
    let (width, height, radius) = (196.0 + 108.0 * amount, 54.0 + 100.0 * amount, 27.0 - amount);
    let scale = pill.scale_factor().map_err(|e| e.to_string())?;
    let size = |v: f64| (v * scale).round() as i32;
    if keep_center {
        let position = pill.outer_position().map_err(|e| e.to_string())?;
        let old = pill.outer_size().map_err(|e| e.to_string())?;
        let x = position.x + (old.width as i32 - size(width)) / 2;
        pill.set_position(tauri::PhysicalPosition::new(x, position.y))
            .map_err(|e| e.to_string())?;
    }
    pill.set_size(tauri::LogicalSize::new(width, height))
        .map_err(|e| e.to_string())?;
    fit_to_work_area(pill).map_err(|e| e.to_string())?;
    {
        use windows_sys::Win32::Graphics::Gdi::{CreateRoundRectRgn, DeleteObject, SetWindowRgn};
        let hwnd = pill.hwnd().map_err(|e| e.to_string())?.0;
        // With a native region, transparent corners cannot intercept desktop clicks.
        unsafe {
            let region = CreateRoundRectRgn(
                0,
                0,
                size(width) + 1,
                size(height) + 1,
                size(radius * 2.0),
                size(radius * 2.0),
            );
            if region.is_null() {
                return Err("Could not shape the floating timer.".into());
            }
            if SetWindowRgn(hwnd, region, 1) == 0 {
                DeleteObject(region);
                return Err("Could not shape the floating timer.".into());
            }
        }
    }
    Ok(())
}

struct DashboardFade {
    hwnd: windows_sys::Win32::Foundation::HWND,
    style: isize,
}

impl DashboardFade {
    fn new(main: &WebviewWindow) -> Option<Self> {
        use windows_sys::Win32::UI::WindowsAndMessaging::*;
        let hwnd = main.hwnd().ok()?.0;
        unsafe {
            let style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
            if style & WS_EX_LAYERED as isize != 0 {
                return None;
            }
            SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED as isize);
            if SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA) == 0 {
                SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style);
                return None;
            }
            Some(Self { hwnd, style })
        }
    }

    fn set_opacity(&self, opacity: f64) {
        use windows_sys::Win32::UI::WindowsAndMessaging::{SetLayeredWindowAttributes, LWA_ALPHA};
        unsafe {
            SetLayeredWindowAttributes(self.hwnd, 0, (opacity * 255.0).round() as u8, LWA_ALPHA);
        }
    }
}

impl Drop for DashboardFade {
    fn drop(&mut self) {
        use windows_sys::Win32::UI::WindowsAndMessaging::{SetWindowLongPtrW, GWL_EXSTYLE};
        unsafe {
            SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, self.style);
        }
    }
}

#[tauri::command]
async fn show_pill(
    app: AppHandle,
    origin: Option<[f64; 2]>,
    reduced_motion: bool,
) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || animate_pill_handoff(app, origin, reduced_motion))
        .await
        .map_err(|e| e.to_string())?
}

fn animate_pill_handoff(
    app: AppHandle,
    origin: Option<[f64; 2]>,
    reduced_motion: bool,
) -> Result<(), String> {
    let main = window(&app, "main")?;
    let pill = window(&app, "pill")?;
    let monitor = main
        .current_monitor()
        .map_err(|e| e.to_string())?
        .or(main.primary_monitor().map_err(|e| e.to_string())?)
        .ok_or("Could not find the dashboard display.")?;
    let area = monitor.work_area();
    let scale = monitor.scale_factor();
    let width = (196.0 * scale).round() as u32;
    let height = (54.0 * scale).round() as u32;
    let clamp = |x: i32, y: i32| {
        PhysicalPosition::new(
            x.clamp(
                area.position.x,
                area.position.x + area.size.width.saturating_sub(width) as i32,
            ),
            y.clamp(
                area.position.y,
                area.position.y + area.size.height.saturating_sub(height) as i32,
            ),
        )
    };
    let target = clamp(
        area.position.x + (area.size.width.saturating_sub(width) / 2) as i32,
        area.position.y + (16.0 * scale).round() as i32,
    );
    let start = match (origin, reduced_motion) {
        (Some([x, y]), false) if x.is_finite() && y.is_finite() => {
            let client = main.inner_position().map_err(|e| e.to_string())?;
            clamp(
                client.x + (x * scale).round() as i32 - width as i32 / 2,
                client.y + (y * scale).round() as i32 - height as i32 / 2,
            )
        }
        _ => target,
    };
    pill.set_position(start).map_err(|e| e.to_string())?;
    resize_pill(&pill, 0.0, false)?;
    pill.set_ignore_cursor_events(true)
        .map_err(|e| e.to_string())?;
    let result = (|| {
        pill.emit_to("pill", "session-handoff", ())
            .map_err(|e| e.to_string())?;
        pill.show().map_err(|e| e.to_string())?;
        let fade = DashboardFade::new(&main);
        let started = Instant::now();
        let duration = if reduced_motion { 0.16 } else { 0.46 };
        loop {
            let time = (started.elapsed().as_secs_f64() / duration).min(1.0);
            let travel = 1.0 - (1.0 - time).powi(3);
            if start != target {
                let x =
                    (start.x as f64 + (target.x as f64 - start.x as f64) * travel).round() as i32;
                let y = (start.y as f64 + (target.y as f64 - start.y as f64) * travel.powf(0.88))
                    .round() as i32;
                pill.set_position(PhysicalPosition::new(x, y))
                    .map_err(|e| e.to_string())?;
            }
            if let Some(fade) = &fade {
                fade.set_opacity(1.0 - ((time - 0.12) / 0.88).clamp(0.0, 1.0));
            }
            if time == 1.0 {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(16));
        }
        main.hide().map_err(|e| e.to_string())?;
        // Let the window thread process the hide before restoring the dashboard's style.
        let _ = main.is_visible();
        Ok(())
    })();
    let _ = pill.set_ignore_cursor_events(false);
    if result.is_err() {
        let _ = pill.hide();
    }
    result
}

#[tauri::command]
fn pill_expand(app: AppHandle, amount: f64) -> Result<(), String> {
    resize_pill(&window(&app, "pill")?, amount, true)
}

#[tauri::command]
fn show_dashboard(app: AppHandle) -> Result<(), String> {
    let main = window(&app, "main")?;
    window(&app, "reminder")?
        .hide()
        .map_err(|e| e.to_string())?;
    close_quit(app.clone())?;
    window(&app, "alarm")?.hide().map_err(|e| e.to_string())?;
    main.show().map_err(|e| e.to_string())?;
    main.unminimize().map_err(|e| e.to_string())?;
    fit_to_work_area(&main).map_err(|e| e.to_string())?;
    main.set_focus().map_err(|e| e.to_string())?;
    window(&app, "pill")?.hide().map_err(|e| e.to_string())
}

struct InstanceGuard(windows_sys::Win32::Foundation::HANDLE);

impl Drop for InstanceGuard {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(self.0);
        }
    }
}

fn single_instance() -> Option<InstanceGuard> {
    use windows_sys::Win32::{
        Foundation::{GetLastError, ERROR_ALREADY_EXISTS},
        System::Threading::CreateMutexW,
    };
    let name: Vec<u16> = "Local\\FocuzzerRustedSession"
        .encode_utf16()
        .chain([0])
        .collect();
    unsafe {
        let handle = CreateMutexW(std::ptr::null(), 0, name.as_ptr());
        if handle.is_null() {
            return None;
        }
        let guard = InstanceGuard(handle);
        (GetLastError() != ERROR_ALREADY_EXISTS).then_some(guard)
    }
}

pub(crate) fn run() {
    let Some(_instance) = single_instance() else {
        return;
    };
    tauri::Builder::default()
        .manage(Session::default())
        .setup(|app| {
            let session = app.state::<Session>();
            *session.audio.lock().unwrap() = Some(focus::start(
                app.handle().clone(),
                session.alarm.clone(),
                session.stopping.clone(),
            ));
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(window.label(), "main" | "pill")
                && matches!(
                    event,
                    tauri::WindowEvent::Moved(_) | tauri::WindowEvent::Resized(_)
                )
            {
                if let Some(webview) = window.app_handle().get_webview_window(window.label()) {
                    let _ = fit_to_work_area(&webview);
                }
            }
            if matches!(window.label(), "reminder" | "pill" | "alarm") {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                }
            }
            if window.label() == "quit" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
            if window.label() == "main" {
                let tauri::WindowEvent::CloseRequested { api, .. } = event else {
                    return;
                };
                api.prevent_close();
                let session = window.state::<Session>();
                if session.stopping.swap(true, Ordering::AcqRel) {
                    return;
                }
                session.alarm.store(false, Ordering::Release);
                for window in window.app_handle().webview_windows().values() {
                    let _ = window.hide();
                }
                let worker = session.audio.lock().ok().and_then(|mut audio| audio.take());
                let play_cue = !session.mute_exit_sound.load(Ordering::Acquire);
                let app = window.app_handle().clone();
                std::thread::spawn(move || {
                    if let Some(worker) = worker {
                        let _ = worker.join();
                    }
                    if play_cue {
                        use windows_sys::Win32::Media::Audio::{
                            PlaySoundW, SND_MEMORY, SND_NODEFAULT,
                        };
                        let cue = include_bytes!("../../ui/sounds/exit.wav");
                        // The buffer contains a RIFF WAVE image and remains valid for this synchronous call.
                        unsafe {
                            PlaySoundW(
                                cue.as_ptr().cast(),
                                std::ptr::null_mut(),
                                SND_MEMORY | SND_NODEFAULT,
                            );
                        }
                    }
                    app.exit(0);
                });
            }
        })
        .invoke_handler(tauri::generate_handler![
            validate_allow_item,
            begin,
            snapshot,
            reminder,
            confirm_studying,
            history,
            delete_session,
            rename_session,
            set_exit_sound,
            quit_code,
            open_quit,
            open_repo,
            close_quit,
            finish,
            show_pill,
            pill_expand,
            show_dashboard
        ])
        .run(tauri::generate_context!())
        .expect("could not start Focuzzer Rusted");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn history_recovers_corruption_and_persists_legacy_ids() {
        let directory = std::env::temp_dir().join(format!("focuzzer-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&directory).unwrap();
        let path = directory.join("sessions.json");
        let backup = directory.join("sessions.bak");
        let second_backup = directory.join("sessions.1.bak");
        fs::write(&path, b"{broken").unwrap();
        assert!(load_history(&path).unwrap().is_empty());
        assert_eq!(fs::read(&backup).unwrap(), b"{broken");
        fs::write(&path, b"{broken again").unwrap();
        assert!(load_history(&path).unwrap().is_empty());
        assert_eq!(fs::read(&second_backup).unwrap(), b"{broken again");
        assert_eq!(fs::read(&backup).unwrap(), b"{broken");

        fs::write(
            &path,
            br#"[{"goal":"Math","minutes":1,"elapsedSeconds":60,"completed":true},
                 {"goal":"English","minutes":1,"elapsedSeconds":60,"completed":true}]"#,
        )
        .unwrap();
        let mut records = load_history(&path).unwrap();
        assert!(records
            .iter()
            .all(|record| uuid::Uuid::parse_str(&record.id).is_ok()));
        assert_ne!(records[0].id, records[1].id);
        let english_id = records[1].id.clone();
        records.remove(0);
        write_history(&path, &records).unwrap();
        assert_eq!(load_history(&path).unwrap()[0].id, english_id);

        for file in [path, backup, second_backup] {
            fs::remove_file(file).unwrap();
        }
        fs::remove_dir(directory).unwrap();
    }
}

#![cfg_attr(windows, windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
#[cfg(windows)]
mod focus;
#[cfg(windows)]
mod quit;

use std::{
    fs,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Instant,
};
use tauri::{AppHandle, Manager, State, WebviewWindow};

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
    #[serde(default)]
    allowed_apps: String,
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

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct Record {
    goal: String,
    minutes: u32,
    elapsed_seconds: u32,
    completed: bool,
    #[serde(default)]
    distractions: u32,
}

#[derive(Default)]
struct Session {
    running: Mutex<Option<Running>>,
    history_write: Mutex<()>,
    alarm: Arc<AtomicBool>,
    stopping: Arc<AtomicBool>,
    audio: Mutex<Option<std::thread::JoinHandle<()>>>,
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
    let mut state = session.running.lock().map_err(|err| err.to_string())?;
    if state.is_some() {
        return Err("A session is already running.".into());
    }
    let rules = focus::website_rules(&plan.sites)?;
    let mut blocked_rules = Vec::new();
    for value in plan
        .blocked_sites
        .split(|c: char| c == ',' || c.is_whitespace())
        .filter(|s| !s.is_empty())
    {
        let host = focus::host(value)
            .ok_or_else(|| format!("Enter a blocked domain or URL for {value}."))?;
        blocked_rules.push(host.trim_start_matches("www.").to_owned());
    }
    *state = Some(Running {
        allowed_apps: plan
            .allowed_apps
            .split([',', '\n'])
            .map(str::trim)
            .filter(|name| !name.is_empty())
            .map(focus::app_name)
            .collect(),
        plan,
        started: Instant::now(),
        rules,
        blocked_rules,
        distractions: 0,
        in_distraction: false,
        blocked_site: None,
        active_tab: None,
        new_tab_since: None,
        check_in: CheckIn::Waiting,
        quit_code: quit::challenge()?,
    });
    Ok(())
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
fn history(app: AppHandle) -> Result<Vec<Record>, String> {
    match fs::read(history_path(&app)?) {
        Ok(bytes) => serde_json::from_slice(&bytes).map_err(|e| e.to_string()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(Vec::new()),
        Err(error) => Err(error.to_string()),
    }
}

#[tauri::command]
fn finish(app: AppHandle, session: State<Session>, code: Option<String>) -> Result<Record, String> {
    let mut state = session.running.lock().map_err(|err| err.to_string())?;
    let running = state.as_ref().ok_or("There is no active session.")?;
    let elapsed = running.started.elapsed().as_secs().min(u32::MAX as u64) as u32;
    let completed = elapsed >= running.plan.minutes * 60;
    if !completed
        && !code.as_deref().is_some_and(|entry| {
            entry == running.quit_code
                || (entry.len() <= 128 && quit::matches_private_command(entry))
        })
    {
        return Err("The code doesn’t match. Check capitalization and try again.".into());
    }
    let record = Record {
        goal: running.plan.goal.clone(),
        minutes: running.plan.minutes,
        elapsed_seconds: elapsed,
        completed,
        distractions: running.distractions,
    };
    let _write = session.history_write.lock().map_err(|e| e.to_string())?;
    let mut records = history(app.clone())?;
    records.push(Record {
        goal: record.goal.clone(),
        ..record
    });
    write_history(&app, &records)?;
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
fn delete_session(app: AppHandle, session: State<Session>, index: usize) -> Result<(), String> {
    let _write = session.history_write.lock().map_err(|e| e.to_string())?;
    let mut records = history(app.clone())?;
    if index >= records.len() {
        return Err("That session is no longer in history.".into());
    }
    records.remove(index);
    write_history(&app, &records)
}

fn write_history(app: &AppHandle, records: &[Record]) -> Result<(), String> {
    let path = history_path(app)?;
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
    #[cfg(windows)]
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

#[tauri::command]
fn show_pill(app: AppHandle) -> Result<(), String> {
    let main = window(&app, "main")?;
    let pill = window(&app, "pill")?;
    if let Some(monitor) = main.current_monitor().map_err(|e| e.to_string())? {
        let scale = monitor.scale_factor();
        let area = monitor.work_area();
        let x = area.position.x + area.size.width as i32 / 2 - (98.0 * scale).round() as i32;
        let y = area.position.y + area.size.height as i32 - (174.0 * scale).round() as i32;
        pill.set_position(tauri::PhysicalPosition::new(x, y))
            .map_err(|e| e.to_string())?;
    }
    resize_pill(&pill, 0.0, false)?;
    pill.show().map_err(|e| e.to_string())?;
    main.hide().map_err(|e| e.to_string())
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

fn main() {
    let Some(_instance) = single_instance() else {
        return;
    };
    tauri::Builder::default()
        .manage(Session::default())
        .setup(|app| {
            #[cfg(windows)]
            {
                let session = app.state::<Session>();
                *session.audio.lock().unwrap() = Some(focus::start(
                    app.handle().clone(),
                    session.alarm.clone(),
                    session.stopping.clone(),
                ));
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == "reminder" {
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
            if window.label() == "main" && matches!(event, tauri::WindowEvent::Destroyed) {
                let session = window.state::<Session>();
                session.stopping.store(true, Ordering::Release);
                if let Ok(mut audio) = session.audio.lock() {
                    if let Some(worker) = audio.take() {
                        let _ = worker.join();
                    }
                }
                window.app_handle().exit(0);
            }
        })
        .invoke_handler(tauri::generate_handler![
            begin,
            snapshot,
            reminder,
            confirm_studying,
            history,
            delete_session,
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

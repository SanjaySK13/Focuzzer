use crate::{CheckIn, Session, CHECK_IN_GRACE};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::{Duration, Instant},
};
use tauri::{AppHandle, Manager};
use windows::{
    core::PWSTR,
    Win32::{
        Foundation::{CloseHandle, HWND, RECT},
        Media::Audio::{
            eConsole, eRender, Endpoints::IAudioEndpointVolume, IMMDeviceEnumerator,
            MMDeviceEnumerator,
        },
        System::{
            Com::{
                CoCreateInstance, CoInitializeEx, CoUninitialize, CLSCTX_ALL, COINIT_MULTITHREADED,
            },
            Diagnostics::Debug::Beep,
            Threading::{
                OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32,
                PROCESS_QUERY_LIMITED_INFORMATION,
            },
        },
        UI::{
            Accessibility::*,
            WindowsAndMessaging::{
                GetForegroundWindow, GetWindowRect, GetWindowTextW, GetWindowThreadProcessId,
            },
        },
    },
};

pub const DEFAULT_SITES: [&str; 7] = [
    "notebooklm.google.com",
    "notebooklm.google",
    "gemini.google.com",
    "chatgpt.com",
    "chat.openai.com",
    "whatsapp.com",
    "web.whatsapp.com",
];

pub fn host(value: &str) -> Option<String> {
    let value = value.trim();
    let input = if value.contains("://") {
        value.to_owned()
    } else {
        format!("https://{value}")
    };
    let parsed = url::Url::parse(&input).ok()?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return None;
    }
    let name = parsed.host_str()?.trim_end_matches('.');
    (name.contains('.') || name == "localhost").then(|| name.to_ascii_lowercase())
}

fn allowed(host: &str, rules: &[String]) -> bool {
    DEFAULT_SITES
        .iter()
        .copied()
        .chain(rules.iter().map(String::as_str))
        .any(|rule| {
            host == rule
                || host
                    .strip_suffix(rule)
                    .is_some_and(|prefix| prefix.ends_with('.'))
        })
}

enum Reading {
    OwnWindow,
    Desktop,
    Unknown(Option<String>),
    Site { host: String, title: Option<String> },
    NewTab,
}

const NEW_TAB_GRACE: Duration = Duration::from_secs(6);

fn tab_title(hwnd: HWND) -> Option<String> {
    let mut buffer = [0u16; 512];
    let length = unsafe { GetWindowTextW(hwnd, &mut buffer) };
    if length <= 0 {
        return None;
    }
    let title = String::from_utf16_lossy(&buffer[..length as usize]);
    let (page, browser) = title.rsplit_once(" - ").unwrap_or((&title, ""));
    let clean = if matches!(
        browser,
        "Brave"
            | "Google Chrome"
            | "Microsoft Edge"
            | "Mozilla Firefox"
            | "Opera"
            | "Vivaldi"
            | "Waterfox"
            | "Arc"
            | "Chromium"
    ) {
        page
    } else {
        &title
    };
    Some(clean.trim().chars().take(100).collect()).filter(|title: &String| !title.is_empty())
}

fn is_new_tab(address: &str) -> bool {
    matches!(
        address.to_ascii_lowercase().trim_end_matches('/'),
        "brave://newtab"
            | "chrome://newtab"
            | "edge://newtab"
            | "vivaldi://newtab"
            | "opera://startpage"
            | "about:newtab"
            | "about:blank"
            | "about:home"
    )
}

type AddressCache = Option<(HWND, IUIAutomationValuePattern)>;

fn foreground(automation: Option<&IUIAutomation>, cache: &mut AddressCache) -> Reading {
    unsafe {
        let hwnd = GetForegroundWindow();
        if hwnd.0.is_null() {
            return Reading::Unknown(None);
        }
        let mut pid = 0;
        GetWindowThreadProcessId(hwnd, Some(&mut pid));
        if pid == std::process::id() {
            return Reading::OwnWindow;
        }
        let Ok(process) = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) else {
            return Reading::Unknown(None);
        };
        let mut path = [0u16; 1024];
        let mut length = path.len() as u32;
        let result = QueryFullProcessImageNameW(
            process,
            PROCESS_NAME_WIN32,
            PWSTR(path.as_mut_ptr()),
            &mut length,
        );
        let _ = CloseHandle(process);
        if result.is_err() {
            return Reading::Unknown(None);
        }
        let name = String::from_utf16_lossy(&path[..length as usize]).to_ascii_lowercase();
        let exe = name.rsplit('\\').next().unwrap_or(&name);
        if !matches!(
            exe,
            "brave.exe"
                | "chrome.exe"
                | "msedge.exe"
                | "firefox.exe"
                | "opera.exe"
                | "opera_gx.exe"
                | "vivaldi.exe"
                | "waterfox.exe"
                | "arc.exe"
                | "chromium.exe"
        ) {
            return Reading::Desktop;
        }
        let title = tab_title(hwnd);
        let result = automation.and_then(|uia| address(uia, hwnd, cache));
        if GetForegroundWindow() != hwnd {
            return Reading::Unknown(None);
        }
        if let Some(host) = result.as_deref().and_then(host) {
            return Reading::Site { host, title };
        }
        if result.as_deref().is_some_and(is_new_tab)
            || title.as_deref().is_some_and(|title| {
                matches!(
                    title.to_ascii_lowercase().as_str(),
                    "new tab" | "new tab page" | "start page" | "speed dial"
                )
            })
        {
            Reading::NewTab
        } else {
            Reading::Unknown(title)
        }
    }
}

unsafe fn address(
    automation: &IUIAutomation,
    hwnd: HWND,
    cache: &mut AddressCache,
) -> Option<String> {
    if let Some((owner, pattern)) = cache {
        if *owner == hwnd {
            if let Ok(value) = pattern.CurrentValue() {
                return Some(value.to_string().trim().to_owned());
            }
        }
    }
    *cache = None;
    let window = automation.ElementFromHandle(hwnd).ok()?;
    let edits = automation
        .CreatePropertyCondition(UIA_ControlTypePropertyId, &(UIA_EditControlTypeId.0.into()))
        .ok()?;
    let candidates = window.FindAll(TreeScope_Descendants, &edits).ok()?;
    let walker = automation.ControlViewWalker().ok()?;
    for index in 0..candidates.Length().ok()? {
        let Ok(edit) = candidates.GetElement(index) else {
            continue;
        };
        let id = edit
            .CurrentAutomationId()
            .map(|id| id.to_string().to_ascii_lowercase())
            .unwrap_or_default();
        let name = edit
            .CurrentName()
            .map(|name| name.to_string().to_ascii_lowercase())
            .unwrap_or_default();
        if !matches!(id.as_str(), "urlbar-input" | "addresseditbox" | "omnibox")
            && ![
                "address bar",
                "address and search bar",
                "enter address",
                "enter an address",
                "type a url",
            ]
            .iter()
            .any(|part| name.contains(part))
        {
            continue;
        }
        let mut parent = walker.GetParentElement(&edit).ok();
        let mut is_page = false;
        while let Some(element) = parent {
            if element.CurrentControlType().ok() == Some(UIA_DocumentControlTypeId) {
                is_page = true;
                break;
            }
            parent = walker.GetParentElement(&element).ok();
        }
        if is_page {
            continue;
        }
        if let Ok(pattern) =
            edit.GetCurrentPatternAs::<IUIAutomationValuePattern>(UIA_ValuePatternId)
        {
            if let Ok(value) = pattern.CurrentValue() {
                *cache = Some((hwnd, pattern));
                return Some(value.to_string().trim().to_owned());
            }
        }
    }
    None
}

struct Volume {
    endpoint: IAudioEndpointVolume,
    level: f32,
    muted: bool,
}

fn size_distraction_banner(window: &tauri::WebviewWindow) {
    let mut rect = RECT::default();
    if unsafe { GetWindowRect(GetForegroundWindow(), &mut rect) }.is_err() {
        return;
    }
    let width = rect.right - rect.left;
    let height = rect.bottom - rect.top;
    if width <= 0 || height <= 0 {
        return;
    }
    let banner_width = (width * 3 / 5).max(1);
    let banner_height = (height * 3 / 5).max(1);
    let _ = window.set_position(tauri::PhysicalPosition::new(
        rect.left + (width - banner_width) / 2,
        rect.top + (height - banner_height) / 2,
    ));
    let _ = window.set_size(tauri::PhysicalSize::new(
        banner_width as u32,
        banner_height as u32,
    ));
}
impl Volume {
    unsafe fn raise() -> windows::core::Result<Self> {
        let enumerator: IMMDeviceEnumerator =
            CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)?;
        let endpoint: IAudioEndpointVolume = enumerator
            .GetDefaultAudioEndpoint(eRender, eConsole)?
            .Activate(CLSCTX_ALL, None)?;
        let volume = Self {
            level: endpoint.GetMasterVolumeLevelScalar()?,
            muted: endpoint.GetMute()?.as_bool(),
            endpoint,
        };
        volume
            .endpoint
            .SetMasterVolumeLevelScalar(1.0, std::ptr::null())?;
        volume.endpoint.SetMute(false, std::ptr::null())?;
        Ok(volume)
    }
}
impl Drop for Volume {
    fn drop(&mut self) {
        unsafe {
            let _ = self
                .endpoint
                .SetMasterVolumeLevelScalar(self.level, std::ptr::null());
            let _ = self.endpoint.SetMute(self.muted, std::ptr::null());
        }
    }
}

pub fn start(
    app: AppHandle,
    active: Arc<AtomicBool>,
    stop: Arc<AtomicBool>,
) -> thread::JoinHandle<()> {
    let alarm = active.clone();
    let shutdown = stop.clone();
    let audio = thread::spawn(move || unsafe {
        let initialized = CoInitializeEx(None, COINIT_MULTITHREADED).is_ok();
        let mut volume = None;
        let mut sounding = false;
        let mut high = true;
        while !shutdown.load(Ordering::Acquire) {
            if alarm.load(Ordering::Acquire) {
                if !sounding {
                    volume = Volume::raise().ok();
                    sounding = true;
                }
                let _ = Beep(if high { 2500 } else { 1850 }, 160);
                high = !high;
                thread::sleep(Duration::from_millis(65));
            } else {
                volume.take();
                sounding = false;
                thread::sleep(Duration::from_millis(35));
            }
        }
        drop(volume);
        if initialized {
            CoUninitialize();
        }
    });
    thread::spawn(move || unsafe {
        let initialized = CoInitializeEx(None, COINIT_MULTITHREADED).is_ok();
        let automation: Option<IUIAutomation> =
            CoCreateInstance(&CUIAutomation, None, CLSCTX_ALL).ok();
        let mut showing = false;
        let mut reminder_visible = false;
        let mut address_cache = None;
        let session = app.state::<Session>();
        while !stop.load(Ordering::Acquire) {
            let running = session.running.lock().ok().and_then(|state| {
                state
                    .as_ref()
                    .filter(|run| run.started.elapsed().as_secs() < (run.plan.minutes * 60) as u64)
                    .map(|run| run.started)
            });
            let reading = running.map(|_| foreground(automation.as_ref(), &mut address_cache));
            let mut blocked = false;
            let mut reminder_pending = false;
            let mut reminder_overdue = false;
            if let Ok(mut state) = session.running.lock() {
                if let Some(run) = state.as_mut().filter(|run| {
                    Some(run.started) == running
                        && run.started.elapsed().as_secs() < (run.plan.minutes * 60) as u64
                }) {
                    match reading {
                        Some(Reading::Site { host, title }) => {
                            run.new_tab_since = None;
                            run.active_tab = title.or_else(|| Some(host.clone()));
                            run.blocked_site = (!allowed(&host, &run.rules)).then_some(host);
                            if run.blocked_site.is_none() {
                                run.in_distraction = false;
                            }
                        }
                        Some(Reading::NewTab) => {
                            run.active_tab = Some("New tab".to_owned());
                            let opened = run.new_tab_since.get_or_insert_with(Instant::now);
                            run.blocked_site = (opened.elapsed() >= NEW_TAB_GRACE)
                                .then(|| "New tab left open".to_owned());
                        }
                        Some(Reading::Desktop) => {
                            run.active_tab = None;
                            run.new_tab_since = None;
                            run.in_distraction = false;
                            run.blocked_site = None;
                        }
                        Some(Reading::Unknown(title)) => {
                            run.active_tab = title;
                            run.new_tab_since = None;
                            run.blocked_site = None;
                        }
                        _ => {}
                    }
                    blocked = run.blocked_site.is_some();
                    if blocked && !run.in_distraction {
                        run.distractions += 1;
                        run.in_distraction = true;
                    }
                    if matches!(run.check_in, CheckIn::Waiting)
                        && run.started.elapsed()
                            >= Duration::from_secs(run.plan.minutes as u64 * 30)
                    {
                        run.check_in = CheckIn::Prompted(Instant::now());
                    }
                    if let CheckIn::Prompted(shown) = run.check_in {
                        reminder_pending = true;
                        reminder_overdue = shown.elapsed() >= CHECK_IN_GRACE;
                    }
                    active.store(blocked || reminder_overdue, Ordering::Release);
                } else {
                    active.store(false, Ordering::Release);
                }
            }
            if showing != blocked {
                if let Some(window) = app.get_webview_window("alarm") {
                    let _ = if blocked {
                        size_distraction_banner(&window);
                        window.show()
                    } else {
                        window.hide()
                    };
                }
                showing = blocked;
                if blocked && reminder_visible && reminder_pending {
                    use windows_sys::Win32::UI::WindowsAndMessaging::{
                        SetWindowPos, HWND_TOPMOST, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE,
                    };
                    if let Some(hwnd) = app
                        .get_webview_window("reminder")
                        .and_then(|window| window.hwnd().ok())
                    {
                        SetWindowPos(
                            hwnd.0,
                            HWND_TOPMOST,
                            0,
                            0,
                            0,
                            0,
                            SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE,
                        );
                    }
                }
            }
            if reminder_visible != reminder_pending {
                if let Some(window) = app.get_webview_window("reminder") {
                    let _ = if reminder_pending {
                        window.show()
                    } else {
                        window.hide()
                    };
                }
                reminder_visible = reminder_pending;
            }
            thread::sleep(Duration::from_millis(90));
        }
        drop(automation);
        if initialized {
            CoUninitialize();
        }
    });
    audio
}

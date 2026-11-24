use super::{
    alarm_volume::{self, Volume},
    CheckIn, Session, CHECK_IN_GRACE,
};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager};
use windows::{
    core::{w, PWSTR},
    Win32::{
        Foundation::{CloseHandle, HWND, RECT},
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
                FindWindowExW, GetAncestor, GetClassNameW, GetForegroundWindow, GetWindowRect,
                GetWindowTextW, GetWindowThreadProcessId, SetWindowPos, GA_ROOTOWNER, HWND_TOPMOST,
                SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE,
            },
        },
    },
};

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

fn domain_matches(host: &str, rule: &str) -> bool {
    host == rule
        || host
            .strip_suffix(rule)
            .is_some_and(|prefix| prefix.ends_with('.'))
}

fn friendly_name(value: &str) -> String {
    value
        .chars()
        .filter(char::is_ascii_alphanumeric)
        .map(|c| c.to_ascii_lowercase())
        .collect()
}

fn one_edit(left: &str, right: &str) -> bool {
    let (shorter, longer) = if left.len() <= right.len() {
        (left.as_bytes(), right.as_bytes())
    } else {
        (right.as_bytes(), left.as_bytes())
    };
    if longer.len() > shorter.len() + 1 {
        return false;
    }
    let first = shorter
        .iter()
        .zip(longer)
        .position(|(a, b)| a != b)
        .unwrap_or(shorter.len());
    first == shorter.len()
        || if shorter.len() == longer.len() {
            shorter[first + 1..] == longer[first + 1..]
        } else {
            shorter[first..] == longer[first + 1..]
        }
}

fn service_domains(value: &str) -> Option<&'static [&'static str]> {
    let lower = value.to_ascii_lowercase();
    let domain = host(value);
    let candidate = domain
        .as_deref()
        .unwrap_or(&lower)
        .trim_start_matches("www.");
    match candidate {
        "notebooklm.google.com" | "notebooklm.google" | "notebook.google.com" => {
            return Some(&["notebooklm.google.com", "notebooklm.google"]);
        }
        "chat.openai.com" => return Some(&["chatgpt.com", "chat.openai.com"]),
        _ => {}
    }
    let key = friendly_name(candidate.strip_suffix(".com").unwrap_or(candidate));
    [
        ("gemini", &["gemini.google.com"][..]),
        (
            "notebooklm",
            &["notebooklm.google.com", "notebooklm.google"][..],
        ),
        ("whatsapp", &["whatsapp.com"][..]),
        ("chatgpt", &["chatgpt.com", "chat.openai.com"][..]),
        ("gmeet", &["meet.google.com"][..]),
        ("googlemeet", &["meet.google.com"][..]),
        ("discord", &["discord.com"][..]),
    ]
    .into_iter()
    .find(|(name, _)| *name == key || (name.len() >= 6 && one_edit(name, &key)))
    .map(|(_, hosts)| hosts)
}

pub fn website_rules(input: &str) -> Result<Vec<String>, String> {
    let mut rules = Vec::new();
    for entry in input
        .split([',', '\n'])
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
    {
        if let Some(domains) = service_domains(entry) {
            rules.extend(domains.iter().map(|domain| (*domain).to_owned()));
        } else {
            for value in entry.split_whitespace() {
                if let Some(domains) = service_domains(value) {
                    rules.extend(domains.iter().map(|domain| (*domain).to_owned()));
                } else {
                    let domain = allowed_website_rule(value)
                        .map_err(|_| format!("Try a website name or full domain for “{value}”."))?;
                    rules.push(domain.trim_start_matches("www.").to_owned());
                }
            }
        }
    }
    rules.sort_unstable();
    rules.dedup();
    Ok(rules)
}

pub fn app_name(value: &str) -> String {
    let value = std::path::Path::new(value)
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or(value);
    let value = value.to_ascii_lowercase();
    let stripped = value.strip_suffix(".exe").unwrap_or(&value);
    let name = friendly_name(stripped);
    match name.as_str() {
        "chatgptapp" | "openaichatgpt" => "chatgpt".into(),
        "visualstudiocode" | "vscode" => "code".into(),
        "word" | "microsoftword" => "winword".into(),
        "microsoftexcel" => "excel".into(),
        "powerpoint" | "microsoftpowerpoint" => "powerpnt".into(),
        "discordapp" => "discord".into(),
        _ => name,
    }
}

pub fn allowed_app_rule(value: &str) -> Result<String, String> {
    let value = value.trim().trim_matches('"');
    let key = app_name(value);
    if key == "systemapps" || key == "windowsutilities" {
        return Ok("system apps".into());
    }
    if desktop_allowed(&key, &[])
        || matches!(key.as_str(), "chatgpt" | "discord" | "spotify" | "codex")
    {
        return Ok(key);
    }
    let path = std::path::Path::new(value);
    let executable = if path.is_absolute()
        && path
            .extension()
            .is_some_and(|ext| ext.eq_ignore_ascii_case("exe"))
        && path.is_file()
    {
        Some(value.to_owned())
    } else if value
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || "._-".contains(c))
        && !value.is_empty()
    {
        let filename = if value.to_ascii_lowercase().ends_with(".exe") {
            value.to_owned()
        } else {
            format!("{value}.exe")
        };
        std::env::var_os("PATH").and_then(|paths| {
            std::env::split_paths(&paths)
                .filter(|dir| dir.is_absolute())
                .map(|dir| dir.join(&filename))
                .find(|path| path.is_file())
                .map(|path| path.to_string_lossy().into_owned())
        })
    } else {
        None
    };
    executable.filter(|name| !name.is_empty()).ok_or_else(|| {
        "Choose a listed app, or paste the full path to its installed .exe file.".into()
    })
}

pub fn allowed_website_rule(value: &str) -> Result<String, String> {
    if let Some(domain) = host(value) {
        match domain.as_str() {
            "web.whatsapp.com" => return Ok("whatsapp.com".into()),
            "notebook.google.com" => return Ok("notebooklm.google.com".into()),
            _ => {}
        }
    }
    if let Some(domains) = service_domains(value.trim()) {
        return Ok(domains[0].to_owned());
    }
    host(value)
        .filter(|name| {
            name == "localhost"
                || name.parse::<std::net::IpAddr>().is_ok()
                || (name.contains('.')
                    && name.len() <= 253
                    && name.rsplit('.').next().is_some_and(|part| {
                        part.len() >= 2 && part.bytes().any(|b| b.is_ascii_alphabetic())
                    })
                    && name.split('.').all(|part| {
                        !part.is_empty()
                            && part.len() <= 63
                            && !part.starts_with('-')
                            && !part.ends_with('-')
                            && part.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
                    }))
        })
        .map(|name| name.trim_start_matches("www.").to_owned())
        .ok_or_else(|| {
            "Choose a listed website, or enter a full domain such as example.edu.".into()
        })
}

fn should_block(host: &str, allowed: &[String], blocked: &[String], blocklist_mode: bool) -> bool {
    blocked.iter().any(|rule| domain_matches(host, rule))
        || (!blocklist_mode && !allowed.iter().any(|rule| domain_matches(host, rule)))
}

enum Reading {
    OwnWindow,
    Desktop {
        exe: String,
        title: Option<String>,
    },
    Unknown,
    UnreadableBrowser {
        exe: String,
        title: Option<String>,
        listed: bool,
    },
    Site {
        host: String,
        title: Option<String>,
    },
    NewTab,
    Editing,
    History,
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

type AddressCache = Option<(HWND, IUIAutomationElement, IUIAutomationValuePattern)>;

fn foreground(automation: Option<&IUIAutomation>, cache: &mut AddressCache) -> Reading {
    unsafe {
        let foreground = GetForegroundWindow();
        if foreground.0.is_null() {
            return Reading::Unknown;
        }
        let owner = GetAncestor(foreground, GA_ROOTOWNER);
        let hwnd = if owner.0.is_null() { foreground } else { owner };
        let pid = window_process_id(hwnd);
        if pid == std::process::id() {
            return Reading::OwnWindow;
        }
        let Some(mut exe) = process_name(pid) else {
            return Reading::Unknown;
        };
        if exe == "applicationframehost" {
            let mut child = None;
            while let Ok(next) =
                FindWindowExW(Some(hwnd), child, w!("Windows.UI.Core.CoreWindow"), None)
            {
                child = Some(next);
                let child_pid = window_process_id(next);
                if child_pid != pid {
                    if let Some(name) = process_name(child_pid) {
                        exe = name;
                        break;
                    }
                }
            }
        }
        let title = tab_title(hwnd);
        let listed = is_browser(&exe);
        if !listed && (desktop_allowed(&exe, &[]) || !browser_window_class(hwnd)) {
            return Reading::Desktop { exe, title };
        }
        let result = automation.and_then(|uia| address(uia, hwnd, cache));
        if GetForegroundWindow() != foreground {
            return Reading::Unknown;
        }
        let (value, editing) = result
            .as_ref()
            .map_or(("", false), |(value, editing)| (value.as_str(), *editing));
        let committed = if editing || value.is_empty() {
            automation.and_then(|uia| committed_document(uia, hwnd))
        } else {
            None
        };
        if GetForegroundWindow() != foreground {
            return Reading::Unknown;
        }
        match classify_address(value, editing, committed.as_deref(), title.clone()) {
            Reading::Unknown => Reading::UnreadableBrowser { exe, title, listed },
            reading => reading,
        }
    }
}

unsafe fn window_process_id(hwnd: HWND) -> u32 {
    let mut pid = 0;
    GetWindowThreadProcessId(hwnd, Some(&mut pid));
    pid
}

unsafe fn process_name(pid: u32) -> Option<String> {
    let process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
    let mut path = [0u16; 1024];
    let mut length = path.len() as u32;
    let result = QueryFullProcessImageNameW(
        process,
        PROCESS_NAME_WIN32,
        PWSTR(path.as_mut_ptr()),
        &mut length,
    );
    let _ = CloseHandle(process);
    result.ok()?;
    let path = String::from_utf16_lossy(&path[..length as usize]);
    let name = path.rsplit('\\').next()?.to_ascii_lowercase();
    Some(name.strip_suffix(".exe").unwrap_or(&name).to_owned())
}

fn is_browser(exe: &str) -> bool {
    matches!(
        exe,
        "brave"
            | "chrome"
            | "msedge"
            | "firefox"
            | "opera"
            | "opera_gx"
            | "vivaldi"
            | "waterfox"
            | "arc"
            | "chromium"
            | "zen"
            | "comet"
            | "librewolf"
            | "floorp"
            | "thorium"
            | "cromite"
            | "browser"
    )
}

unsafe fn browser_window_class(hwnd: HWND) -> bool {
    let mut name = [0; 128];
    let length = GetClassNameW(hwnd, &mut name).max(0) as usize;
    matches!(
        String::from_utf16_lossy(&name[..length]).as_str(),
        "Chrome_WidgetWin_1" | "MozillaWindowClass"
    )
}

fn classify_address(
    value: &str,
    editing: bool,
    committed: Option<&str>,
    title: Option<String>,
) -> Reading {
    let verified_edit = editing
        && committed
            .and_then(host)
            .zip(host(value))
            .is_some_and(|(document, entered)| {
                document.trim_start_matches("www.") == entered.trim_start_matches("www.")
            });
    let address = if verified_edit || !editing {
        committed.unwrap_or(value)
    } else {
        value
    };
    let new_tab = is_new_tab(value)
        || title.as_deref().is_some_and(|title| {
            matches!(
                title.to_ascii_lowercase().as_str(),
                "new tab" | "new tab page" | "start page" | "speed dial"
            )
        });
    if editing && !verified_edit && !(new_tab && (value.is_empty() || is_new_tab(value))) {
        return Reading::Editing;
    }
    if let Some(host) = host(address) {
        return Reading::Site { host, title };
    }
    if new_tab {
        Reading::NewTab
    } else if matches!(
        value.to_ascii_lowercase().trim_end_matches('/'),
        "brave://history"
            | "chrome://history"
            | "edge://history"
            | "vivaldi://history"
            | "opera://history"
    ) {
        Reading::History
    } else {
        Reading::Unknown
    }
}

fn committed_document(automation: &IUIAutomation, hwnd: HWND) -> Option<String> {
    unsafe {
        let window = automation.ElementFromHandle(hwnd).ok()?;
        let condition = automation
            .CreatePropertyCondition(
                UIA_ControlTypePropertyId,
                &UIA_DocumentControlTypeId.0.into(),
            )
            .ok()?;
        let doc = window.FindFirst(TreeScope_Descendants, &condition).ok()?;
        let url = doc
            .GetCurrentPatternAs::<IUIAutomationValuePattern>(UIA_ValuePatternId)
            .and_then(|pattern| pattern.CurrentValue())
            .or_else(|_| {
                doc.GetCurrentPatternAs::<IUIAutomationLegacyIAccessiblePattern>(
                    UIA_LegacyIAccessiblePatternId,
                )
                .and_then(|pattern| pattern.CurrentValue())
            })
            .ok()?
            .to_string();
        host(&url)?;
        Some(url)
    }
}

fn desktop_allowed(exe: &str, custom: &[String]) -> bool {
    if exe == "applicationframehost" {
        return false;
    }
    custom.iter().any(|name| name == &app_name(exe))
        || matches!(
            exe,
            "explorer"
                | "shellhost"
                | "shellexperiencehost"
                | "startmenuexperiencehost"
                | "searchhost"
                | "searchapp"
                | "systemsettings"
                | "systemsettingsbroker"
                | "taskmgr"
                | "lockapp"
                | "textinputhost"
                | "snippingtool"
                | "screenclippinghost"
                | "dwm"
                | "ctfmon"
                | "smartscreen"
                | "windowsterminal"
                | "openconsole"
                | "conhost"
                | "cmd"
                | "powershell"
                | "pwsh"
                | "notepad"
                | "notepad++"
                | "code"
                | "code-insiders"
                | "cursor"
                | "obsidian"
                | "notion"
                | "onenote"
                | "winword"
                | "excel"
                | "powerpnt"
                | "soffice"
                | "soffice.bin"
                | "acrobat"
                | "acrord32"
                | "sumatrapdf"
                | "foxitpdfreader"
                | "calc"
                | "calculatorapp"
                | "anki"
                | "zotero"
                | "whatsapp"
                | "discord"
        )
}

unsafe fn address(
    automation: &IUIAutomation,
    hwnd: HWND,
    cache: &mut AddressCache,
) -> Option<(String, bool)> {
    if let Some((owner, edit, pattern)) = cache {
        if *owner == hwnd {
            if let Ok(value) = pattern.CurrentValue() {
                if let Ok(focused) = edit.CurrentHasKeyboardFocus() {
                    return Some((value.to_string().trim().to_owned(), focused.as_bool()));
                }
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
    let mut fallback = None;
    let mut ambiguous = false;
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
        let named_address = matches!(
            id.as_str(),
            "urlbar-input" | "urlbar" | "addresseditbox" | "omnibox" | "addressbar"
        ) || [
            "address bar",
            "address and search bar",
            "enter address",
            "enter an address",
            "type a url",
        ]
        .iter()
        .any(|part| name.contains(part));
        let mut parent = walker.GetParentElement(&edit).ok();
        let mut is_page = false;
        let mut is_toolbar = false;
        while let Some(element) = parent {
            let control = element.CurrentControlType().ok();
            if control == Some(UIA_DocumentControlTypeId) {
                is_page = true;
                break;
            }
            is_toolbar |= control == Some(UIA_ToolBarControlTypeId);
            parent = walker.GetParentElement(&element).ok();
        }
        if is_page || !(named_address || is_toolbar) {
            continue;
        }
        if let Ok(pattern) =
            edit.GetCurrentPatternAs::<IUIAutomationValuePattern>(UIA_ValuePatternId)
        {
            if let Ok(value) = pattern.CurrentValue() {
                let Ok(focus) = edit.CurrentHasKeyboardFocus() else {
                    continue;
                };
                let focused = focus.as_bool();
                let value = value.to_string().trim().to_owned();
                if named_address {
                    *cache = Some((hwnd, edit, pattern));
                    return Some((value, focused));
                }
                if !focused && value.contains("://") && host(&value).is_some() {
                    ambiguous |= fallback.replace((value, false)).is_some();
                }
            }
        }
    }
    if ambiguous {
        None
    } else {
        fallback
    }
}

fn foreground_bounds() -> Option<RECT> {
    let mut rect = RECT::default();
    unsafe { GetWindowRect(GetForegroundWindow(), &mut rect).ok()? };
    Some(rect)
}

fn size_distraction_banner(window: &tauri::WebviewWindow, rect: RECT) {
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
pub fn start(
    app: AppHandle,
    active: Arc<AtomicBool>,
    stop: Arc<AtomicBool>,
) -> thread::JoinHandle<()> {
    let alarm = active.clone();
    let shutdown = stop.clone();
    let journal = app
        .path()
        .app_local_data_dir()
        .ok()
        .map(|dir| dir.join("alarm-volume.json"));
    let audio = thread::spawn(move || unsafe {
        let beep_alarm = alarm.clone();
        let beep_shutdown = shutdown.clone();
        let beeper = thread::spawn(move || {
            let mut high = true;
            while !beep_shutdown.load(Ordering::Acquire) {
                if beep_alarm.load(Ordering::Acquire) {
                    let _ = Beep(if high { 2500 } else { 1850 }, 160);
                    high = !high;
                    thread::sleep(Duration::from_millis(65));
                } else {
                    thread::sleep(Duration::from_millis(35));
                }
            }
        });
        let initialized = CoInitializeEx(None, COINIT_MULTITHREADED).is_ok();
        let mut volume: Option<Volume> = None;
        let mut next_attempt = Instant::now();
        let mut was_alarming = false;
        while !shutdown.load(Ordering::Acquire) {
            let alarming = alarm.load(Ordering::Acquire);
            if alarming != was_alarming {
                next_attempt = Instant::now();
                was_alarming = alarming;
            }
            if alarming {
                if volume
                    .as_ref()
                    .is_some_and(|current| current.enforce().is_err())
                {
                    volume.take();
                }
                if volume.is_none() && Instant::now() >= next_attempt {
                    volume = journal.as_deref().and_then(|path| Volume::begin(path).ok());
                    if volume.is_none() {
                        next_attempt = Instant::now() + Duration::from_secs(1);
                    }
                }
            } else {
                volume.take();
                if Instant::now() >= next_attempt {
                    if let Some(path) = journal.as_deref() {
                        let _ = alarm_volume::recover(path);
                    }
                    next_attempt = Instant::now() + Duration::from_secs(1);
                }
            }
            thread::sleep(Duration::from_millis(35));
        }
        drop(volume);
        if initialized {
            CoUninitialize();
        }
        let _ = beeper.join();
    });
    thread::spawn(move || unsafe {
        let initialized = CoInitializeEx(None, COINIT_MULTITHREADED).is_ok();
        let automation: Option<IUIAutomation> =
            CoCreateInstance(&CUIAutomation, None, CLSCTX_ALL).ok();
        let mut address_cache = None;
        let mut last_blocked_area = None;
        let session = app.state::<Session>();
        while !stop.load(Ordering::Acquire) {
            let running = session.running.lock().ok().and_then(|state| {
                state
                    .as_ref()
                    .filter(|run| run.started.elapsed().as_secs() < (run.plan.minutes * 60) as u64)
                    .map(|run| run.started)
            });
            let reading = running.map(|_| foreground(automation.as_ref(), &mut address_cache));
            let outside_app = matches!(
                &reading,
                Some(
                    Reading::Site { .. }
                        | Reading::History
                        | Reading::Desktop { .. }
                        | Reading::UnreadableBrowser { .. }
                        | Reading::NewTab
                )
            );
            let mut blocked = false;
            let mut reminder_pending = false;
            let mut reminder_overdue = false;
            if let Ok(mut state) = session.running.lock() {
                if let Some(run) = state.as_mut().filter(|run| {
                    Some(run.started) == running
                        && run.started.elapsed().as_secs() < (run.plan.minutes * 60) as u64
                }) {
                    if !matches!(
                        &reading,
                        Some(Reading::UnreadableBrowser { .. } | Reading::Unknown)
                    ) {
                        run.unreadable_since = None;
                    }
                    match reading {
                        Some(Reading::Site { host, title }) => {
                            run.new_tab_since = None;
                            run.active_tab = title.or_else(|| Some(host.clone()));
                            run.blocked_site = should_block(
                                &host,
                                &run.rules,
                                &run.blocked_rules,
                                run.plan.blocklist_mode,
                            )
                            .then_some(host);
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
                        Some(Reading::History) => {
                            run.active_tab = Some("Browser history".into());
                            run.new_tab_since = None;
                            run.blocked_site = Some("Browser history".into());
                        }
                        Some(Reading::Editing) => {
                            run.active_tab = Some("Typing address".into());
                            run.new_tab_since = None;
                            run.blocked_site = None;
                        }
                        Some(Reading::Desktop { exe, title }) => {
                            run.active_tab = title.or_else(|| Some(format!("{exe}.exe")));
                            run.new_tab_since = None;
                            run.blocked_site = (!desktop_allowed(&exe, &run.allowed_apps))
                                .then(|| format!("Desktop app: {exe}.exe"));
                            if run.blocked_site.is_none() {
                                run.in_distraction = false;
                            }
                        }
                        Some(Reading::UnreadableBrowser { exe, title, listed }) => {
                            run.active_tab =
                                title.or_else(|| Some(format!("Address unavailable · {exe}")));
                            run.new_tab_since = None;
                            let since = run.unreadable_since.get_or_insert_with(Instant::now);
                            let warn = run.plan.warn_unreadable_browser
                                && (listed || !desktop_allowed(&exe, &run.allowed_apps));
                            run.blocked_site = if warn {
                                (since.elapsed() >= Duration::from_secs(2))
                                    .then(|| format!("Could not verify browser address: {exe}"))
                            } else {
                                (!listed && !desktop_allowed(&exe, &run.allowed_apps))
                                    .then(|| format!("Desktop app: {exe}.exe"))
                            };
                            if run.blocked_site.is_none() {
                                run.in_distraction = false;
                            }
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
                        let _ = app.emit("checkin-start", ());
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
            if blocked && outside_app {
                last_blocked_area = foreground_bounds();
            }
            if blocked
                || reminder_pending
                || overlay_visible(&app, "alarm")
                || overlay_visible(&app, "reminder")
            {
                let handle = app.clone();
                let area = last_blocked_area;
                let _ = app.run_on_main_thread(move || {
                    let (alarm, reminder) = overlay_targets(
                        blocked,
                        reminder_pending,
                        overlay_visible(&handle, "quit"),
                    );
                    if let Some(window) = handle.get_webview_window("alarm") {
                        let visible = window.is_visible().unwrap_or(false);
                        if !alarm && visible {
                            let _ = window.hide();
                        }
                    }
                    if let Some(window) = handle.get_webview_window("reminder") {
                        let visible = window.is_visible().unwrap_or(false);
                        if reminder && !visible {
                            let _ = window.show();
                        }
                        if !reminder && visible {
                            let _ = window.hide();
                        }
                    }
                    if alarm {
                        if let Some(window) = handle.get_webview_window("alarm") {
                            if !window.is_visible().unwrap_or(false) {
                                if let Some(area) = area {
                                    size_distraction_banner(&window, area);
                                }
                                let _ = window.show();
                            }
                        }
                    }
                });
            }
            thread::sleep(Duration::from_millis(90));
            // Re-assert pill always-on-top every ~2 seconds to prevent other apps overriding it
            static TOPMOST_COUNTER: std::sync::atomic::AtomicU32 =
                std::sync::atomic::AtomicU32::new(0);
            let count = TOPMOST_COUNTER.fetch_add(1, Ordering::Relaxed);
            if count % 22 == 0 {
                // roughly every 2 seconds (22 * 90ms)
                if let Some(pill) = app.get_webview_window("pill") {
                    if pill.is_visible().unwrap_or(false) {
                        if let Ok(hwnd) = pill.hwnd() {
                            let _ = SetWindowPos(
                                hwnd,
                                Some(HWND_TOPMOST),
                                0,
                                0,
                                0,
                                0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                            );
                        }
                    }
                }
            }
        }
        drop(automation);
        if initialized {
            CoUninitialize();
        }
    });
    audio
}

fn overlay_visible(app: &AppHandle, label: &str) -> bool {
    app.get_webview_window(label)
        .is_some_and(|window| window.is_visible().unwrap_or(false))
}

fn overlay_targets(blocked: bool, reminder_pending: bool, quit_visible: bool) -> (bool, bool) {
    (
        blocked && !reminder_pending && !quit_visible,
        reminder_pending && !quit_visible,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allow_items_reject_junk_and_canonicalize_valid_entries() {
        assert!(allowed_app_rule("sonn").is_err());
        assert!(allowed_app_rule("random-application-4681.exe").is_err());
        assert_eq!(allowed_app_rule("Spotify.exe").unwrap(), "spotify");
        assert_eq!(allowed_app_rule("ChatGPT App").unwrap(), "chatgpt");
        let installed = std::env::current_exe().unwrap();
        assert_eq!(
            allowed_app_rule(installed.to_str().unwrap()).unwrap(),
            installed.to_str().unwrap()
        );
        assert!(allowed_website_rule("random text").is_err());
        assert!(allowed_website_rule("sonn").is_err());
        assert!(allowed_website_rule("invalid..com").is_err());
        assert_eq!(
            allowed_website_rule("https://www.example.edu/path").unwrap(),
            "example.edu"
        );
        assert_eq!(
            allowed_website_rule("notebook.google.com").unwrap(),
            "notebooklm.google.com"
        );
        assert_eq!(allowed_website_rule("whatsap.com").unwrap(), "whatsapp.com");
    }

    #[test]
    fn friendly_inputs_resolve_to_canonical_rules() {
        let rules =
            website_rules("gemini, Notebook LM, whatsap.com, gmeet.com, example.edu").unwrap();
        assert!(rules.iter().any(|rule| rule == "gemini.google.com"));
        assert!(rules.iter().any(|rule| rule == "notebooklm.google.com"));
        assert!(rules.iter().any(|rule| rule == "whatsapp.com"));
        assert!(!rules.iter().any(|rule| rule == "whatsap.com"));
        assert!(rules.iter().any(|rule| rule == "meet.google.com"));
        assert!(rules.iter().any(|rule| rule == "example.edu"));
        assert!(desktop_allowed("chatgpt", &[app_name("ChatGPT app")]));
    }

    #[test]
    fn allowed_website_presets_require_selection() {
        let allowed = website_rules("whatsap.com, chatgpt.com").unwrap();
        let blocked = vec!["whatsapp.com".into()];
        for host in ["whatsapp.com", "web.whatsapp.com"] {
            assert!(should_block(host, &[], &[], false));
            assert!(!should_block(host, &allowed, &[], false));
            assert!(should_block(host, &allowed, &blocked, false));
            assert!(!should_block(host, &[], &[], true));
        }
        assert!(!should_block("chat.openai.com", &allowed, &[], false));
        assert!(should_block(
            "whatsapp.com.example.com",
            &allowed,
            &[],
            false
        ));
    }

    #[test]
    fn standard_study_and_shell_apps_are_allowed() {
        assert!(desktop_allowed("explorer", &[]));
        assert!(!desktop_allowed("applicationframehost", &[]));
        assert!(!desktop_allowed(
            "applicationframehost",
            &["applicationframehost".into()]
        ));
        assert!(is_browser("zen") && is_browser("comet"));
        assert!(desktop_allowed("winword", &[]));
        assert!(!desktop_allowed("codex", &[]));
        assert!(desktop_allowed("codex", &["codex".into()]));
        assert!(!desktop_allowed("steam", &[]));
    }

    #[test]
    fn typed_address_does_not_replace_the_committed_page() {
        assert!(matches!(
            classify_address(
                "google.com/search?q=test",
                true,
                Some("https://chatgpt.com/c/123"),
                None
            ),
            Reading::Editing
        ));
        assert!(matches!(
            classify_address("google.com/search?q=test", true, Some("https://www.google.com/search?q=test"), None),
            Reading::Site { host, .. } if host == "www.google.com"
        ));
        assert!(matches!(
            classify_address("www.google.com/search?q=test", true, Some("https://www.google.com/search?q=test"), None),
            Reading::Site { host, .. } if host == "www.google.com"
        ));
        assert!(matches!(
            classify_address("", false, Some("https://chatgpt.com/c/123"), None),
            Reading::Site { host, .. } if host == "chatgpt.com"
        ));
    }

    #[test]
    fn overlay_priorities_are_exclusive() {
        assert_eq!(overlay_targets(true, false, false), (true, false));
        assert_eq!(overlay_targets(true, true, false), (false, true));
        assert_eq!(overlay_targets(true, true, true), (false, false));
        assert_eq!(overlay_targets(false, false, false), (false, false));
    }
}

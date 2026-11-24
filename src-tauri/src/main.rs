#![cfg_attr(windows, windows_subsystem = "windows")]

#[cfg(windows)]
mod desktop;
#[cfg(windows)]
mod quit;

#[cfg(windows)]
fn main() {
    desktop::run();
}

#[cfg(not(windows))]
fn main() {
    eprintln!("Focuzzer Rusted requires Windows.");
}

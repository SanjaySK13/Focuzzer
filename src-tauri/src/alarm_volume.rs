use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File},
    io::{self, Write},
    path::{Path, PathBuf},
    time::Instant,
};
use windows::{
    core::PCWSTR,
    Win32::{
        Media::Audio::{
            eConsole, eRender, Endpoints::IAudioEndpointVolume, IMMDeviceEnumerator,
            MMDeviceEnumerator,
        },
        System::Com::{CoCreateInstance, CoTaskMemFree, CLSCTX_ALL},
    },
};

#[derive(Serialize, Deserialize)]
struct SavedVolume {
    device: String,
    level: f32,
    muted: bool,
}

pub(super) struct Volume {
    endpoint: IAudioEndpointVolume,
    saved: SavedVolume,
    journal: PathBuf,
    started: Instant,
}

unsafe fn devices() -> windows::core::Result<IMMDeviceEnumerator> {
    CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)
}

impl SavedVolume {
    unsafe fn restore(&self, endpoint: &IAudioEndpointVolume) -> windows::core::Result<()> {
        endpoint.SetMasterVolumeLevelScalar(self.level, std::ptr::null())?;
        endpoint.SetMute(self.muted, std::ptr::null())
    }
}

pub(super) unsafe fn recover(journal: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let bytes = match fs::read(journal) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error.into()),
    };
    let saved: SavedVolume = serde_json::from_slice(&bytes)?;
    if !(0.0..=1.0).contains(&saved.level) || saved.device.is_empty() || saved.device.contains('\0')
    {
        return Err("Invalid alarm volume recovery data.".into());
    }
    let device: Vec<u16> = saved.device.encode_utf16().chain([0]).collect();
    let endpoint = devices()?
        .GetDevice(PCWSTR(device.as_ptr()))?
        .Activate(CLSCTX_ALL, None)?;
    saved.restore(&endpoint)?;
    fs::remove_file(journal)?;
    Ok(())
}

impl Volume {
    pub(super) unsafe fn begin(journal: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        recover(journal)?;
        let device = devices()?.GetDefaultAudioEndpoint(eRender, eConsole)?;
        let endpoint: IAudioEndpointVolume = device.Activate(CLSCTX_ALL, None)?;
        let id = device.GetId()?;
        let device = id.to_string();
        CoTaskMemFree(Some(id.0.cast()));
        let saved = SavedVolume {
            device: device?,
            level: endpoint.GetMasterVolumeLevelScalar()?,
            muted: endpoint.GetMute()?.as_bool(),
        };
        fs::create_dir_all(
            journal
                .parent()
                .ok_or("Missing volume recovery directory.")?,
        )?;
        let temporary = journal.with_extension("tmp");
        let mut file = File::create(&temporary)?;
        file.write_all(&serde_json::to_vec(&saved)?)?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temporary, journal)?;
        Ok(Self {
            endpoint,
            saved,
            journal: journal.into(),
            started: Instant::now(),
        })
    }

    pub(super) unsafe fn enforce(&self) -> windows::core::Result<()> {
        let progress = (self.started.elapsed().as_secs_f32() / 0.75).min(1.0);
        let target = self.saved.level + (1.0 - self.saved.level) * progress;
        if self.endpoint.GetMasterVolumeLevelScalar()? < target {
            self.endpoint
                .SetMasterVolumeLevelScalar(target, std::ptr::null())?;
        }
        if self.endpoint.GetMute()?.as_bool() {
            self.endpoint.SetMute(false, std::ptr::null())?;
        }
        Ok(())
    }
}

impl Drop for Volume {
    fn drop(&mut self) {
        if unsafe { self.saved.restore(&self.endpoint) }.is_ok() {
            let _ = fs::remove_file(&self.journal);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn invalid_recovery_data_is_preserved_without_touching_audio() {
        let path =
            std::env::temp_dir().join(format!("focuzzer-volume-{}.json", uuid::Uuid::new_v4()));
        let invalid = br#"{"device":"endpoint","level":2.0,"muted":true}"#;
        fs::write(&path, invalid).unwrap();
        let result = unsafe { recover(&path) };
        assert!(result.is_err());
        assert_eq!(fs::read(&path).unwrap(), invalid);
        fs::remove_file(&path).unwrap();
        assert!(unsafe { recover(&path) }.is_ok());
    }
}

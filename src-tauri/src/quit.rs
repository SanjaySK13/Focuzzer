use std::{fs, path::PathBuf, ptr::null_mut};
use windows_sys::Win32::Security::Cryptography::{
    BCryptCloseAlgorithmProvider, BCryptDeriveKeyPBKDF2, BCryptGenRandom,
    BCryptOpenAlgorithmProvider, BCRYPT_ALG_HANDLE_HMAC_FLAG, BCRYPT_SHA256_ALGORITHM,
    BCRYPT_USE_SYSTEM_PREFERRED_RNG,
};

pub fn challenge() -> Result<String, String> {
    let mut bytes = [0u8; 26];
    let alphabet = b"23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ!@#$%&*?=";
    let result = unsafe {
        BCryptGenRandom(
            null_mut(),
            bytes.as_mut_ptr(),
            bytes.len() as u32,
            BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        )
    };
    if result < 0 {
        return Err("Windows could not generate the quit code.".into());
    }
    Ok(bytes
        .iter()
        .map(|byte| char::from(alphabet[*byte as usize % alphabet.len()]))
        .collect())
}

fn decode<const N: usize>(hex: &str) -> Option<[u8; N]> {
    let mut value = [0u8; N];
    if hex.len() != N * 2 || !hex.is_ascii() {
        return None;
    }
    for (index, byte) in value.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&hex[index * 2..index * 2 + 2], 16).ok()?;
    }
    Some(value)
}

pub fn matches_private_command(candidate: &str) -> bool {
    fn read_verifier() -> Option<([u8; 16], [u8; 32])> {
        let profile = PathBuf::from(std::env::var_os("USERPROFILE")?);
        let path = profile.join("AppData/Local/Focuzzer/.focuzzer-private-exit");
        let content = fs::read_to_string(path).ok()?;
        let (salt, digest) = content.trim().split_once(':')?;
        Some((decode(salt)?, decode(digest)?))
    }
    let Some((salt, expected)) = read_verifier() else {
        return false;
    };
    let mut provider = null_mut();
    let mut derived = [0u8; 32];
    unsafe {
        if BCryptOpenAlgorithmProvider(
            &mut provider,
            BCRYPT_SHA256_ALGORITHM,
            std::ptr::null(),
            BCRYPT_ALG_HANDLE_HMAC_FLAG,
        ) < 0
        {
            return false;
        }
        let status = BCryptDeriveKeyPBKDF2(
            provider,
            candidate.as_ptr(),
            candidate.len() as u32,
            salt.as_ptr(),
            salt.len() as u32,
            200_000,
            derived.as_mut_ptr(),
            derived.len() as u32,
            0,
        );
        BCryptCloseAlgorithmProvider(provider, 0);
        status >= 0
            && derived
                .iter()
                .zip(expected)
                .fold(0u8, |diff, (actual, expected)| diff | (actual ^ expected))
                == 0
    }
}

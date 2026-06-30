# IRA Portable — biometric & voice (honest security model)

This documents the **real** secure-unlock path for the portable demo. It does NOT
claim a universal "fingerprint unlocks the USB" feature — that does not exist
portably, and saying so would be dishonest.

## The secure path (layered, OS/hardware-backed)

```
[1] Encrypted volume on the stick   →  unlocked by the OS / hardware biometric
        VeraCrypt | BitLocker | macOS APFS encryption | Linux LUKS
                                        (Windows Hello, Touch ID, etc.)
                                  ↓
[2] IRA master password             →  portable/verify_master_password.py
        bcrypt + lockout (V2·Phase 2)
                                  ↓
[3] IRA running, local-first        →  portable_demo guard rail (V2·Phase 1)
```

- **Layer 1 is where biometrics actually live.** The biometric never travels with
  the stick or unlocks IRA directly; it unlocks an OS-managed encrypted *volume*
  using a key sealed by the platform (TPM/Secure Enclave). The biometric is matched
  by the operating system, not by IRA.
- **Layer 2 is IRA's own gate** — the master password (encrypted at rest, lockout
  on repeated failure). Required to launch regardless of how the volume was unlocked.
- **Layer 3** keeps the running system local-first and gated.

Why no "biometric USB unlock": a USB stick has no trusted sensor or secure element
of its own. A fingerprint can only gate access *through* a host OS that owns the
sensor and the key store. Any product claiming the stick itself is biometric-locked
is really relying on the host — so we make that dependency explicit instead of
hiding it.

## Per-OS encrypted-volume bring-up

| OS | Mechanism | Biometric unlock |
|---|---|---|
| Windows | BitLocker To Go, or VeraCrypt volume | Windows Hello unlocks the key |
| macOS | Encrypted APFS volume, or VeraCrypt | Touch ID unlocks the key |
| Linux | LUMS/LUKS container, or VeraCrypt | fprintd / PAM where configured |

After the volume mounts, run the normal launcher
(`portable/start_ira_<os>.{sh,ps1}`); it verifies the master password before boot.

## Voice as OPTIONAL second factor (off by default)

IRA already verifies an owner voiceprint (ECAPA, fail-closed) in the voice pipeline.
For the portable demo this is an **optional 2FA only**, never a primary unlock:

- Flag: `IRA_PORTABLE_VOICE_2FA` — **default `false`**. When false, the demo gates on
  the master password alone.
- When `true`, a matching owner voiceprint is required *in addition to* the master
  password — it can never replace it.

> **Anti-spoof warning.** A voiceprint is not a secret: it can be recorded and
> replayed, and modern voice cloning lowers the bar further. Treat voice strictly
> as a convenience second factor behind the master password and the OS-encrypted
> volume — never as the sole gate, and never for high-value actions on its own.

## What this demo does NOT claim

- It does not claim the USB unlocks by fingerprint on its own.
- It does not claim voice alone authenticates the owner.
- It does not store any biometric template in IRA's portable bundle.

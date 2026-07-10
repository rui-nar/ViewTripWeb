# Phase 1 crypto spike — results & locked stack (issue #26)

Throwaway harness: `spike/e2ee_spike/` (pure-Dart `cryptography_plus`, so the *same*
code runs on Dart VM and web — see `lib/e2ee_spike.dart`, `test/`).

## What was proven (here, on Windows: VM + Chrome)

| Check | VM | Web (Chrome/JS) | Result |
|---|---|---|---|
| Content encrypt→decrypt round-trip (XChaCha20-Poly1305) | ✅ | ✅ | pass |
| Wrong CMK / wrong recovery secret rejected | ✅ | ✅ | pass |
| Tampered ciphertext → AEAD auth failure (no silent garbage) | ✅ | ✅ | pass |
| Option A — recovery-key wrap/unwrap (HKDF) | ✅ | ✅ | pass |
| Option B — Q&A → Argon2id wrap/unwrap | ✅ | ✅ | pass |
| Q&A answer normalization tolerance ("  St. " ~ "st.") | ✅ | ✅ | pass |
| Device wrap — X25519 ECDH (enables cross-device re-wrap) | ✅ | ✅ | pass |
| **Cross-platform interop: VM-produced ciphertext decrypts on web** | ✅ | ✅ | **byte-compatible** |

11/11 tests pass on both VM and web (`dart test`, `dart test -p chrome`).

## Argon2id timing (median of 3, after warm-up)

| Params | VM (native) | Web (Chrome, pure-Dart JS) |
|---|---|---|
| 19 MiB, t=2, p=1 | 134 ms | 864 ms |
| 32 MiB, t=3, p=1 | 338 ms | 2348 ms |
| 64 MiB, t=3, p=1 | 713 ms | 4282 ms |

Interpretation: native is healthy at strong params. Pure-Dart Argon2id on web is the
slow path the research warned about. **But Argon2id is only used for Option B (Q&A)
recovery — a rare backstop, not daily login** — so a ~1–2 s web derive is acceptable.
For production, prefer WASM Argon2 (`dargon2_flutter`, hash-wasm on web) to allow
stronger params, with PBKDF2-WebCrypto (≥600k iters) as the web fallback if WASM
integration is painful. Store a per-platform KDF id so wraps stay interoperable.

## Locked stack (v1)

- **AEAD:** XChaCha20-Poly1305 (192-bit random nonce; safe random nonces at scale).
- **Key wrapping:** AEAD-wrap (encrypt the key). Per-item random DEK wrapped by the CMK;
  CMK wrapped by each recovery method + each device.
- **Subkey derivation / domain separation:** HKDF-SHA256 with distinct `info` strings.
- **Device wrap:** X25519 ECDH (ephemeral) → HKDF → AEAD. Lets any holder of the CMK
  re-wrap it to a new device's *public* key — the basis for passwordless device approval.
- **Option A recovery:** 256-bit CSPRNG recovery secret (BIP39 phrase/file) → HKDF wrap.
- **Option B recovery:** normalized Q&A → Argon2id → wrap. Library for production:
  `dargon2_flutter` (native mobile + WASM web); `cryptography_plus` for AEAD/HKDF/X25519.
- **Server:** stores only opaque blobs; performs no crypto.

## Gate verdict: GREEN to proceed to Phase 2

Architecture and primitives validated; ciphertext is byte-compatible across the two
targets reachable here.

## Still requires the user's hardware (cannot run on this Windows box)

These do NOT block Phase 2 (server schema) but MUST be confirmed before production release:
1. **Android + iOS Argon2id timing** on a low-end device (confirm ≤~1–2 s for Q&A recovery).
2. **Native↔web cross-IMPLEMENTATION interop** once production swaps in `dargon2_flutter`
   (native C on mobile) / WASM on web — verify byte-compat vs the pure-Dart baseline here.
3. **Web secure-storage** behaviour for the device private key (flutter_secure_storage /
   non-extractable WebCrypto key) and what happens when site data is cleared (confirms the
   recovery path is mandatory on web).
4. **Web bundle-size delta** and `flutter build web --wasm` compatibility with the chosen libs.
5. **Web Worker / isolate offload** for the KDF so a slow derive never freezes the UI.

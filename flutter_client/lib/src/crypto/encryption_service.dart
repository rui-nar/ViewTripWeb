/// Orchestrates the client side of zero-knowledge encryption (issue #26):
/// enabling encryption, and unlocking the Content Master Key (CMK) on a trusted
/// device. Crypto comes from [e2ee_crypto]; device-key persistence and the
/// server API are injected interfaces, so this service is unit-testable with
/// fakes and carries no Flutter / dart:io / http dependency itself.
library;

import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography_plus/cryptography_plus.dart';

import 'e2ee_crypto.dart';

/// Persists this device's X25519 key pair in the OS keystore. The concrete
/// implementation (flutter_secure_storage / WebCrypto) is a thin I/O adapter
/// supplied by the app; this service never touches storage directly.
abstract class DeviceKeyStore {
  Future<SimpleKeyPair?> load();
  Future<void> save(SimpleKeyPair keyPair);
}

/// Encryption state for the current account + this device, from GET /status.
class EncryptionStatus {
  final bool enabled;
  final List<String> recoveryMethods;
  final bool deviceRegistered;
  final bool deviceApproved;
  final String? wrappedCmkB64;
  final String? ephemeralPublicKeyB64;

  const EncryptionStatus({
    required this.enabled,
    required this.recoveryMethods,
    required this.deviceRegistered,
    required this.deviceApproved,
    this.wrappedCmkB64,
    this.ephemeralPublicKeyB64,
  });
}

/// A device awaiting approval (from GET /devices/pending).
class PendingDevice {
  final String publicKeyB64;
  final String label;
  const PendingDevice(this.publicKeyB64, this.label);
}

/// The server endpoints this service needs. Implemented by the app's HTTP layer.
abstract class EncryptionApi {
  Future<EncryptionStatus> fetchStatus(String? devicePublicKeyB64);
  Future<void> enable(Map<String, dynamic> payload);
  Future<void> registerDevice(String publicKeyB64, String label);
  Future<List<PendingDevice>> pendingDevices();
  Future<void> approveDevice(
      String publicKeyB64, String wrappedCmkB64, String ephemeralPublicKeyB64);
}

/// The user's recovery choice at enable-time (the honest A/B decision).
sealed class RecoveryChoice {
  const RecoveryChoice();
}

/// Option A — a high-entropy recovery key the app generates and shows once.
class RecoveryKeyChoice extends RecoveryChoice {
  const RecoveryKeyChoice();
}

/// Medium — security questions; weaker, hardened with Argon2id.
class QnaChoice extends RecoveryChoice {
  final List<String> answers;
  const QnaChoice(this.answers);
}

/// High — a user passphrase (Argon2id over the raw passphrase). Recovery-only.
class PassphraseChoice extends RecoveryChoice {
  final String passphrase;
  const PassphraseChoice(this.passphrase);
}

/// Result of enabling encryption. For Option A, [recoverySecret] is the
/// one-time secret the UI must display and then discard (the app never keeps it
/// in plaintext). Null for Option B.
class EnableResult {
  final Uint8List? recoverySecret;
  const EnableResult(this.recoverySecret);
}

class EncryptionService {
  final DeviceKeyStore _store;
  final EncryptionApi _api;
  final String deviceLabel;

  EncryptionService(this._store, this._api, {this.deviceLabel = ''});

  SecretKey? _cmk;

  /// True once the CMK is held in memory (this device can read/write ciphertext).
  bool get isUnlocked => _cmk != null;

  /// Drop the in-memory CMK (e.g. on logout).
  void lock() => _cmk = null;

  /// Enable encryption for the account: generate a CMK, wrap it to this device
  /// and to the chosen recovery method, push the wraps to the server, and hold
  /// the CMK unlocked. Returns the one-time recovery secret for Option A.
  Future<EnableResult> enable(RecoveryChoice choice) async {
    final cmk = await generateCmk();

    final keyPair = await _store.load() ?? await generateDeviceKeyPair();
    await _store.save(keyPair);
    final devicePub = await keyPair.extractPublicKey();
    final deviceWrap = await wrapCmkToDevicePublicKey(cmk, devicePub);

    final salt = _randomBytes(16);
    Uint8List? recoverySecret;
    final WrappedCmk recoveryWrap;
    final String method;
    String? kdfParamsJson;

    switch (choice) {
      case RecoveryKeyChoice():
        recoverySecret = generateRecoverySecret();
        recoveryWrap = await wrapCmkWithRecoveryKey(cmk, recoverySecret, salt);
        method = 'recovery_key';
      case PassphraseChoice(passphrase: final passphrase):
        const params = Argon2Params();
        recoveryWrap = await wrapCmkWithPassphrase(cmk, passphrase, salt, params);
        method = 'passphrase';
        kdfParamsJson = jsonEncode(params.toJson());
      case QnaChoice(answers: final answers):
        const params = Argon2Params();
        recoveryWrap = await wrapCmkWithQna(cmk, answers, salt, params);
        method = 'qna';
        kdfParamsJson = jsonEncode(params.toJson());
    }

    await _api.enable({
      'device': {
        'public_key': base64.encode(devicePub.bytes),
        'label': deviceLabel,
        'wrapped_cmk': base64.encode(deviceWrap.blob),
        'ephemeral_public_key': base64.encode(deviceWrap.ephemeralPublicKey!),
      },
      'recovery': {
        'method': method,
        'wrapped_cmk': base64.encode(recoveryWrap.blob),
        'salt': base64.encode(salt),
        'kdf_params_json': kdfParamsJson,
      },
    });

    _cmk = cmk;
    return EnableResult(recoverySecret);
  }

  /// Try to unlock on a trusted device: load the stored key pair, ask the server
  /// for this device's wrapped CMK, and unwrap it. Returns false if there is no
  /// stored key, encryption is off, or this device is not yet approved — those
  /// cases fall through to device-approval (Phase 5) or recovery (Phase 6).
  Future<bool> unlock() async {
    final keyPair = await _store.load();
    if (keyPair == null) return false;

    final pub = await keyPair.extractPublicKey();
    final status = await _api.fetchStatus(base64.encode(pub.bytes));
    if (!status.enabled) return false;
    if (!status.deviceApproved || status.wrappedCmkB64 == null) return false;

    final wrapped = WrappedCmk(
      base64.decode(status.wrappedCmkB64!),
      ephemeralPublicKey: base64.decode(status.ephemeralPublicKeyB64!),
    );
    _cmk = await unwrapCmkWithDeviceKeyPair(wrapped, keyPair);
    return true;
  }

  // ── Cross-device approval (trusted-device model) ──────────────────────────

  /// Register THIS device for approval: ensure a device key pair exists locally,
  /// then post its public key as pending. A trusted device approves it later;
  /// afterwards [unlock] succeeds. Call when [unlock] returned false because the
  /// device isn't registered/approved yet.
  Future<void> registerThisDevice({String label = ''}) async {
    final keyPair = await _store.load() ?? await generateDeviceKeyPair();
    await _store.save(keyPair);
    final pub = await keyPair.extractPublicKey();
    await _api.registerDevice(
        base64.encode(pub.bytes), label.isEmpty ? deviceLabel : label);
  }

  /// Devices awaiting approval on this account (shown on a trusted device).
  Future<List<PendingDevice>> pendingDevices() => _api.pendingDevices();

  /// Approve a pending device by wrapping the CMK to its public key. Requires an
  /// unlocked CMK — which only a trusted device has, so only it can approve.
  Future<void> approveDevice(String devicePublicKeyB64) async {
    final cmk = _requireCmk();
    final pub = SimplePublicKey(base64.decode(devicePublicKeyB64),
        type: KeyPairType.x25519);
    final wrapped = await wrapCmkToDevicePublicKey(cmk, pub);
    await _api.approveDevice(
      devicePublicKeyB64,
      base64.encode(wrapped.blob),
      base64.encode(wrapped.ephemeralPublicKey!),
    );
  }

  /// Encrypt a text field to a stored envelope. Requires [isUnlocked].
  Future<String> encryptText(String plaintext) async {
    final enc = await encryptField(plaintext, _requireCmk());
    return enc.encode();
  }

  /// Decrypt a stored envelope. Requires [isUnlocked]; throws on wrong key/tamper.
  Future<String> decryptText(String envelope) =>
      decryptField(EncryptedField.decode(envelope), _requireCmk());

  // ── CRUD-boundary helpers (used by the notifiers) ─────────────────────────

  /// Encrypt a field for storage when encryption is unlocked; otherwise pass it
  /// through unchanged (encryption off, or locked → store plaintext as before).
  Future<String?> protect(String? plaintext) async {
    if (plaintext == null || plaintext.isEmpty || !isUnlocked) return plaintext;
    return encryptText(plaintext);
  }

  /// Reveal a stored field: decrypt when it's an encrypted envelope and we're
  /// unlocked; otherwise return it unchanged (plaintext, or still-locked
  /// ciphertext the caller renders as locked). Never throws.
  Future<String?> reveal(String? value) async {
    if (value == null || !EncryptedField.isEnvelope(value) || !isUnlocked) {
      return value;
    }
    try {
      return await decryptText(value);
    } catch (_) {
      return value; // wrong key / corrupt — surface as-is rather than crash
    }
  }

  SecretKey _requireCmk() {
    final cmk = _cmk;
    if (cmk == null) {
      throw StateError('Encryption is locked — unlock the CMK first');
    }
    return cmk;
  }

  Uint8List _randomBytes(int n) {
    final rnd = Random.secure();
    return Uint8List.fromList(List<int>.generate(n, (_) => rnd.nextInt(256)));
  }
}

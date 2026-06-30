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

/// The server endpoints this service needs. Implemented by the app's HTTP layer.
abstract class EncryptionApi {
  Future<EncryptionStatus> fetchStatus(String? devicePublicKeyB64);
  Future<void> enable(Map<String, dynamic> payload);
}

/// The user's recovery choice at enable-time (the honest A/B decision).
sealed class RecoveryChoice {
  const RecoveryChoice();
}

/// Option A — a high-entropy recovery key the app generates and shows once.
class RecoveryKeyChoice extends RecoveryChoice {
  const RecoveryKeyChoice();
}

/// Option B — security questions; weaker, hardened with Argon2id.
class QnaChoice extends RecoveryChoice {
  final List<String> answers;
  const QnaChoice(this.answers);
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

  /// Encrypt a text field to a stored envelope. Requires [isUnlocked].
  Future<String> encryptText(String plaintext) async {
    final enc = await encryptField(plaintext, _requireCmk());
    return enc.encode();
  }

  /// Decrypt a stored envelope. Requires [isUnlocked]; throws on wrong key/tamper.
  Future<String> decryptText(String envelope) =>
      decryptField(EncryptedField.decode(envelope), _requireCmk());

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

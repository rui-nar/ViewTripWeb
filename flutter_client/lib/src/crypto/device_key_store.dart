/// Device-key persistence for E2EE (issue #26).
///
/// The device's X25519 private key lives in the OS keystore and never leaves
/// the device. Storage is abstracted behind [SecureKvStore] so the serialization
/// logic is unit-testable headless; the concrete keystore binding
/// ([FlutterSecureKvStore]) is a thin wrapper over flutter_secure_storage.
///
/// NB (web): on Flutter web the keystore is backed by browser storage — clearing
/// site data wipes the device key, which is exactly why a recovery method is
/// mandatory. Confirm web behaviour on real targets (Phase 1 device-matrix item).
library;

import 'dart:convert';

import 'package:cryptography_plus/cryptography_plus.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'encryption_service.dart';

/// Minimal secure key/value backing. Abstracted so tests inject an in-memory map.
abstract class SecureKvStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
}

/// [DeviceKeyStore] backed by a [SecureKvStore], persisting the X25519 private
/// key as its 32-byte seed (base64). Reconstructs the key pair on load.
class SecureStorageDeviceKeyStore implements DeviceKeyStore {
  final SecureKvStore _kv;
  static const _seedKey = 'e2ee_device_x25519_seed_v1';
  final _x25519 = X25519();

  SecureStorageDeviceKeyStore(this._kv);

  @override
  Future<SimpleKeyPair?> load() async {
    final b64 = await _kv.read(_seedKey);
    if (b64 == null) return null;
    return _x25519.newKeyPairFromSeed(base64.decode(b64));
  }

  @override
  Future<void> save(SimpleKeyPair keyPair) async {
    final seed = await keyPair.extractPrivateKeyBytes();
    await _kv.write(_seedKey, base64.encode(seed));
  }

  Future<void> clear() => _kv.delete(_seedKey);
}

/// Concrete keystore binding over flutter_secure_storage (OS keystore /
/// Keychain / encrypted browser storage). Thin by design.
class FlutterSecureKvStore implements SecureKvStore {
  final FlutterSecureStorage _storage;
  FlutterSecureKvStore([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  @override
  Future<String?> read(String key) => _storage.read(key: key);

  @override
  Future<void> write(String key, String value) =>
      _storage.write(key: key, value: value);

  @override
  Future<void> delete(String key) => _storage.delete(key: key);
}

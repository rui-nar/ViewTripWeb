import 'dart:convert';

import 'package:cryptography_plus/cryptography_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/crypto/encryption_service.dart';

/// In-memory device key store (the real one persists to the OS keystore).
class FakeDeviceKeyStore implements DeviceKeyStore {
  SimpleKeyPair? _kp;
  @override
  Future<SimpleKeyPair?> load() async => _kp;
  @override
  Future<void> save(SimpleKeyPair keyPair) async => _kp = keyPair;
}

/// Fake server that records the enable payload and serves it back from /status,
/// so the device enable -> later-session unlock path is exercised end to end.
class FakeEncryptionApi implements EncryptionApi {
  Map<String, dynamic>? enablePayload;
  bool deviceApproved = true; // emulate the enabling device being trusted

  @override
  Future<void> enable(Map<String, dynamic> payload) async {
    enablePayload = payload;
  }

  @override
  Future<EncryptionStatus> fetchStatus(String? devicePublicKeyB64) async {
    final p = enablePayload;
    if (p == null) {
      return const EncryptionStatus(
        enabled: false, recoveryMethods: [],
        deviceRegistered: false, deviceApproved: false,
      );
    }
    final device = p['device'] as Map<String, dynamic>;
    final isThisDevice = device['public_key'] == devicePublicKeyB64;
    return EncryptionStatus(
      enabled: true,
      recoveryMethods: [(p['recovery'] as Map<String, dynamic>)['method'] as String],
      deviceRegistered: isThisDevice,
      deviceApproved: isThisDevice && deviceApproved,
      wrappedCmkB64: isThisDevice ? device['wrapped_cmk'] as String : null,
      ephemeralPublicKeyB64:
          isThisDevice ? device['ephemeral_public_key'] as String : null,
    );
  }
}

void main() {
  group('enable', () {
    test('Option A returns a one-time recovery secret and posts a valid payload',
        () async {
      final api = FakeEncryptionApi();
      final svc = EncryptionService(FakeDeviceKeyStore(), api, deviceLabel: 'Test');
      final result = await svc.enable(const RecoveryKeyChoice());

      expect(result.recoverySecret, isNotNull);
      expect(result.recoverySecret!.length, 32);
      expect(svc.isUnlocked, isTrue);

      final payload = api.enablePayload!;
      expect((payload['recovery'] as Map)['method'], 'recovery_key');
      expect((payload['recovery'] as Map)['kdf_params_json'], isNull);
      final device = payload['device'] as Map;
      // all blobs are valid base64
      for (final k in ['public_key', 'wrapped_cmk', 'ephemeral_public_key']) {
        expect(() => base64.decode(device[k] as String), returnsNormally);
      }
      expect(device['label'], 'Test');
    });

    test('Medium (Q&A) posts qna + Argon2id params and no recovery secret', () async {
      final api = FakeEncryptionApi();
      final svc = EncryptionService(FakeDeviceKeyStore(), api);
      final result = await svc.enable(const QnaChoice(['Fluffy', 'Lisbon', 'Smith']));

      expect(result.recoverySecret, isNull);
      expect(svc.isUnlocked, isTrue);
      final recovery = api.enablePayload!['recovery'] as Map;
      expect(recovery['method'], 'qna');
      expect(recovery['kdf_params_json'], isNotNull);
    });

    test('High (passphrase) posts passphrase + params and no recovery secret', () async {
      final api = FakeEncryptionApi();
      final svc = EncryptionService(FakeDeviceKeyStore(), api);
      final result =
          await svc.enable(const PassphraseChoice('correct horse battery staple'));

      expect(result.recoverySecret, isNull);
      expect(svc.isUnlocked, isTrue);
      final recovery = api.enablePayload!['recovery'] as Map;
      expect(recovery['method'], 'passphrase');
      expect(recovery['kdf_params_json'], isNotNull);
    });
  });

  group('unlock', () {
    test('a trusted device unlocks the CMK in a fresh session and round-trips',
        () async {
      final api = FakeEncryptionApi();
      final store = FakeDeviceKeyStore(); // persists across "sessions"

      // Session 1: enable + encrypt something.
      final svc1 = EncryptionService(store, api);
      await svc1.enable(const RecoveryKeyChoice());
      final envelope = await svc1.encryptText('Honeymoon 2025');

      // Session 2: a brand-new service over the SAME store unlocks via the device.
      final svc2 = EncryptionService(store, api);
      expect(svc2.isUnlocked, isFalse);
      expect(await svc2.unlock(), isTrue);
      expect(await svc2.decryptText(envelope), 'Honeymoon 2025');
    });

    test('no stored device key -> cannot unlock', () async {
      final api = FakeEncryptionApi()..enablePayload = null;
      final svc = EncryptionService(FakeDeviceKeyStore(), api);
      expect(await svc.unlock(), isFalse);
    });

    test('device present but not yet approved -> cannot unlock', () async {
      final api = FakeEncryptionApi();
      final store = FakeDeviceKeyStore();
      await EncryptionService(store, api).enable(const RecoveryKeyChoice());
      api.deviceApproved = false; // server has not approved this device

      final svc = EncryptionService(store, api);
      expect(await svc.unlock(), isFalse);
    });
  });

  test('encrypt/decrypt throws while locked', () async {
    final svc = EncryptionService(FakeDeviceKeyStore(), FakeEncryptionApi());
    expect(() => svc.encryptText('x'), throwsStateError);
  });
}

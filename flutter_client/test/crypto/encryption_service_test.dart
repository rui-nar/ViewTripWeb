import 'dart:convert';

import 'package:cryptography_plus/cryptography_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/crypto/e2ee_crypto.dart';
import 'package:viewtrip_client/src/crypto/encryption_service.dart';

/// In-memory device key store (the real one persists to the OS keystore).
class FakeDeviceKeyStore implements DeviceKeyStore {
  SimpleKeyPair? _kp;
  @override
  Future<SimpleKeyPair?> load() async => _kp;
  @override
  Future<void> save(SimpleKeyPair keyPair) async => _kp = keyPair;
}

class _FakeDev {
  final bool approved;
  final String? wrappedCmk;
  final String? ephemeral;
  _FakeDev(this.approved, this.wrappedCmk, this.ephemeral);
}

/// In-memory fake server: tracks devices (pubkey -> state) so the full
/// enable / register / approve / unlock lifecycle runs end to end.
class FakeEncryptionApi implements EncryptionApi {
  Map<String, dynamic>? enablePayload;
  bool _enabled = false;
  final _devices = <String, _FakeDev>{};
  final _recovery = <String>[];

  @override
  Future<void> enable(Map<String, dynamic> payload) async {
    enablePayload = payload;
    _enabled = true;
    final d = payload['device'] as Map<String, dynamic>;
    _devices[d['public_key'] as String] = _FakeDev(
        true, d['wrapped_cmk'] as String, d['ephemeral_public_key'] as String);
    _recovery.add((payload['recovery'] as Map)['method'] as String);
  }

  @override
  Future<EncryptionStatus> fetchStatus(String? devicePublicKeyB64) async {
    final dev = devicePublicKeyB64 == null ? null : _devices[devicePublicKeyB64];
    return EncryptionStatus(
      enabled: _enabled,
      recoveryMethods: List.of(_recovery),
      deviceRegistered: dev != null,
      deviceApproved: dev?.approved ?? false,
      wrappedCmkB64: dev?.wrappedCmk,
      ephemeralPublicKeyB64: dev?.ephemeral,
    );
  }

  @override
  Future<void> registerDevice(String publicKeyB64, String label) async {
    _devices.putIfAbsent(publicKeyB64, () => _FakeDev(false, null, null));
  }

  @override
  Future<List<PendingDevice>> pendingDevices() async => _devices.entries
      .where((e) => !e.value.approved)
      .map((e) => PendingDevice(e.key, ''))
      .toList();

  @override
  Future<void> approveDevice(
      String publicKeyB64, String wrappedCmkB64, String ephemeralPublicKeyB64) async {
    _devices[publicKeyB64] = _FakeDev(true, wrappedCmkB64, ephemeralPublicKeyB64);
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

    test('registered but not yet approved -> cannot unlock', () async {
      final api = FakeEncryptionApi();
      // Device A enables encryption (different store).
      await EncryptionService(FakeDeviceKeyStore(), api)
          .enable(const RecoveryKeyChoice());
      // Device B registers and stays pending.
      final svcB = EncryptionService(FakeDeviceKeyStore(), api);
      await svcB.registerThisDevice();
      expect(await svcB.unlock(), isFalse);
    });
  });

  group('cross-device approval', () {
    test('B registers, A approves, B unlocks and reads A\'s ciphertext', () async {
      final api = FakeEncryptionApi();
      final svcA = EncryptionService(FakeDeviceKeyStore(), api);
      await svcA.enable(const RecoveryKeyChoice());
      final envelope = await svcA.encryptText('Trip to Japan');

      final svcB = EncryptionService(FakeDeviceKeyStore(), api);
      await svcB.registerThisDevice();
      expect(await svcB.unlock(), isFalse); // pending

      final pending = await svcA.pendingDevices();
      expect(pending.length, 1);
      await svcA.approveDevice(pending.first.publicKeyB64); // re-wrap CMK to B

      expect(await svcB.unlock(), isTrue);
      expect(await svcB.decryptText(envelope), 'Trip to Japan');
    });

    test('approving requires an unlocked CMK', () async {
      final api = FakeEncryptionApi();
      final svc = EncryptionService(FakeDeviceKeyStore(), api); // never unlocked
      expect(() => svc.approveDevice('SOME_PUBKEY'), throwsStateError);
    });
  });

  test('encrypt/decrypt throws while locked', () async {
    final svc = EncryptionService(FakeDeviceKeyStore(), FakeEncryptionApi());
    expect(() => svc.encryptText('x'), throwsStateError);
  });

  group('protect/reveal (CRUD boundary)', () {
    test('locked: protect and reveal pass through unchanged', () async {
      final svc = EncryptionService(FakeDeviceKeyStore(), FakeEncryptionApi());
      expect(await svc.protect('hello'), 'hello');
      expect(await svc.reveal('hello'), 'hello');
    });

    test('unlocked: protect produces an envelope; reveal round-trips', () async {
      final svc = EncryptionService(FakeDeviceKeyStore(), FakeEncryptionApi());
      await svc.enable(const RecoveryKeyChoice());

      final protectedVal = await svc.protect('Honeymoon 2025');
      expect(protectedVal, isNot('Honeymoon 2025'));
      expect(EncryptedField.isEnvelope(protectedVal!), isTrue);
      expect(await svc.reveal(protectedVal), 'Honeymoon 2025');
    });

    test('unlocked: reveal leaves plaintext (non-envelope) untouched', () async {
      final svc = EncryptionService(FakeDeviceKeyStore(), FakeEncryptionApi());
      await svc.enable(const RecoveryKeyChoice());
      expect(await svc.reveal('v1.2 release notes'), 'v1.2 release notes');
      expect(await svc.protect(null), isNull);
      expect(await svc.protect(''), '');
    });
  });
}

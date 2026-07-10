import 'dart:convert';
import 'dart:typed_data';

import 'package:e2ee_spike/e2ee_spike.dart';
import 'package:test/test.dart';

final _salt = Uint8List.fromList(List<int>.generate(16, (i) => i * 7 % 256));
const _params = Argon2Params(memoryKib: 19456, iterations: 2, parallelism: 1);

void main() {
  group('content round-trip via CMK', () {
    test('encrypt then decrypt returns the original text', () async {
      final cmk = await generateCmk();
      const text = 'Sunset over the Dolomites 🏔️ — felt unreal.';
      final enc = await encryptField(text, cmk);
      expect(await decryptField(enc, cmk), text);
    });

    test('wrong CMK cannot decrypt', () async {
      final cmk = await generateCmk();
      final other = await generateCmk();
      final enc = await encryptField('secret', cmk);
      expect(() => decryptField(enc, other), throwsA(isA<Object>()));
    });

    test('tampered ciphertext fails AEAD auth (no silent garbage)', () async {
      final cmk = await generateCmk();
      final enc = await encryptField('secret', cmk);
      enc.ciphertext[enc.ciphertext.length - 1] ^= 0x01; // flip a tag byte
      expect(() => decryptField(enc, cmk), throwsA(isA<Object>()));
    });
  });

  group('Option A — recovery key wrap', () {
    test('wrap then unwrap recovers the CMK', () async {
      final cmk = await generateCmk();
      final secret = generateRecoverySecret();
      final w = await wrapCmkWithRecoveryKey(cmk, secret, _salt);
      final cmk2 = await unwrapCmkWithRecoveryKey(w, secret, _salt);
      // prove it's the same key by decrypting content wrapped under the original
      final enc = await encryptField('hello', cmk);
      expect(await decryptField(enc, cmk2), 'hello');
    });

    test('wrong recovery key is rejected', () async {
      final cmk = await generateCmk();
      final w = await wrapCmkWithRecoveryKey(cmk, generateRecoverySecret(), _salt);
      expect(() => unwrapCmkWithRecoveryKey(w, generateRecoverySecret(), _salt),
          throwsA(isA<Object>()));
    });
  });

  group('Option B — Q&A wrap (Argon2id)', () {
    final answers = ['Fluffy', 'Lisbon', 'Mrs. Object'];

    test('wrap then unwrap recovers the CMK', () async {
      final cmk = await generateCmk();
      final w = await wrapCmkWithQna(cmk, answers, _salt, _params);
      final cmk2 = await unwrapCmkWithQna(w, answers, _salt, _params);
      final enc = await encryptField('hi', cmk);
      expect(await decryptField(enc, cmk2), 'hi');
    });

    test('answer normalization tolerates spacing/case variance', () async {
      final cmk = await generateCmk();
      final w = await wrapCmkWithQna(cmk, answers, _salt, _params);
      final messy = ['  fluffy ', 'LISBON', 'mrs.   object'];
      final cmk2 = await unwrapCmkWithQna(w, messy, _salt, _params);
      final enc = await encryptField('hi', cmk);
      expect(await decryptField(enc, cmk2), 'hi');
    });

    test('genuinely wrong answers are rejected', () async {
      final cmk = await generateCmk();
      final w = await wrapCmkWithQna(cmk, answers, _salt, _params);
      expect(
          () => unwrapCmkWithQna(w, ['x', 'y', 'z'], _salt, _params),
          throwsA(isA<Object>()));
    });
  });

  group('Device wrap — X25519 (cross-device re-wrap)', () {
    test('CMK wrapped to a device public key unwraps with its private key',
        () async {
      final cmk = await generateCmk();
      final device = await generateDeviceKeyPair();
      final pub = await device.extractPublicKey();
      final w = await wrapCmkToDevicePublicKey(cmk, pub); // "approve device"
      final cmk2 = await unwrapCmkWithDeviceKeyPair(w, device);
      final enc = await encryptField('x', cmk);
      expect(await decryptField(enc, cmk2), 'x');
    });

    test('another device cannot unwrap', () async {
      final cmk = await generateCmk();
      final deviceA = await generateDeviceKeyPair();
      final deviceB = await generateDeviceKeyPair();
      final pubA = await deviceA.extractPublicKey();
      final w = await wrapCmkToDevicePublicKey(cmk, pubA);
      expect(() => unwrapCmkWithDeviceKeyPair(w, deviceB),
          throwsA(isA<Object>()));
    });
  });

  group('cross-platform interop (VM <-> web)', () {
    // Fixture generated once on the Dart VM (see bin/gen_fixture.dart). This
    // same test runs under `dart test` (VM) and `dart test -p chrome` (web);
    // both must decrypt it -> proves byte-compatible ciphertext across targets.
    test('decrypts a fixture produced on another platform', () async {
      final fx = jsonDecode(_fixtureJson) as Map<String, dynamic>;
      final secret = base64.decode(fx['recoverySecret'] as String);
      final salt = base64.decode(fx['salt'] as String);
      final w = WrappedCmk(base64.decode(fx['wrappedCmk'] as String));
      final cmk = await unwrapCmkWithRecoveryKey(w, secret, salt);
      final enc = EncryptedField.fromJson(
          jsonDecode(fx['field'] as String) as Map<String, dynamic>);
      expect(await decryptField(enc, cmk), fx['plaintext']);
    });
  });
}

/// Replace with the output of `dart run bin/gen_fixture.dart`.
const _fixtureJson =
    r'''{"recoverySecret":"8GfTtuuU9ty/32BZofE5jev/NywCkRywrxlMEUmGFHQ=","salt":"AAcOFRwjKjE4P0ZNVFtiaQ==","wrappedCmk":"dE42hsQvvSm9IV3b71pxOfKQ/sc0KxdgXsjr5wXAPf/Vu5P6N1GnncoXzdALyZQUvbKK4hUYqT0s6g7uZ6Vp3a4P5E17q2Yf","field":"{\"k\":\"IJUQ9iEPwVw34OuKV9vOIHYzEVT/0S8SRhttovfAShPCWPi3uUgg9iCEh8jaOxCJ5l5DGgFOl4fZRFqb75eX/m2U8EViHEuU\",\"c\":\"Brzd0YAv5lBKfcfUDuNYT+50Jvc2wRPVP7N875xfsyY5DzcBYZ+SNJ6rzDVZQJ0scRSX8DWQPlnr/rmyYwnAT9fSwS6nYioqq4OBsptTT5MTl0RYTb6kPMomDZKoFg==\"}","plaintext":"interop check — café, Москва, 日本語, 🚲"}''';

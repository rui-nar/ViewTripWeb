import 'dart:convert';
import 'dart:typed_data';

import 'package:e2ee_spike/e2ee_spike.dart';

/// Generates an interop fixture: a CMK wrapped under a recovery secret, plus a
/// content field encrypted under that CMK. Paste the printed JSON into the
/// `_fixtureJson` const in test/crypto_spike_test.dart, then run that test on
/// both `dart test` (VM) and `dart test -p chrome` (web) to prove the
/// ciphertext is byte-compatible across targets.
Future<void> main() async {
  final salt = Uint8List.fromList(List<int>.generate(16, (i) => i * 7 % 256));
  final secret = generateRecoverySecret();
  final cmk = await generateCmk();
  final wrapped = await wrapCmkWithRecoveryKey(cmk, secret, salt);
  const plaintext = 'interop check — café, Москва, 日本語, 🚲';
  final field = await encryptField(plaintext, cmk);

  final fixture = {
    'recoverySecret': base64.encode(secret),
    'salt': base64.encode(salt),
    'wrappedCmk': base64.encode(wrapped.blob),
    'field': jsonEncode(field.toJson()),
    'plaintext': plaintext,
  };
  print(jsonEncode(fixture));
}

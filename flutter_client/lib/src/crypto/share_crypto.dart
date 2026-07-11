/// Key-agnostic encrypt/decrypt helpers for a per-share content key (issue #28).
///
/// A share content key has NO relationship to the account CMK or unlock
/// state — an anonymous share-link viewer never has a CMK, only whatever key
/// material is embedded in the URL fragment (`#key=...`, which never reaches
/// the server). These are thin wrappers around e2ee_crypto.dart's
/// `encryptField`/`decryptField`, which already accept an arbitrary
/// [SecretKey] despite being named for CMK use, plus base64 helpers for
/// embedding the key in a URL fragment.
library;

import 'dart:convert';

import 'package:cryptography_plus/cryptography_plus.dart';

import 'e2ee_crypto.dart';

/// Generate a fresh random per-share content key (same primitive as
/// [generateCmk] — a 256-bit XChaCha20-Poly1305 key).
Future<SecretKey> generateShareKey() => generateCmk();

/// Encrypt [plaintext] under [key], returning the `v1.<b64>.<b64>` envelope.
Future<String> encryptTextWithKey(String plaintext, SecretKey key) async {
  final field = await encryptField(plaintext, key);
  return field.encode();
}

/// Decrypt an envelope produced by [encryptTextWithKey]. Throws on a wrong
/// key, tampered ciphertext, or malformed envelope.
Future<String> decryptTextWithKey(String envelope, SecretKey key) async {
  final field = EncryptedField.decode(envelope);
  return decryptField(field, key);
}

/// Encode a share key as URL-safe base64 for embedding in a share URL
/// fragment (`#key=...`).
Future<String> shareKeyToBase64(SecretKey key) async {
  final bytes = await key.extractBytes();
  return base64Url.encode(bytes);
}

/// Decode a share key from the base64 produced by [shareKeyToBase64].
SecretKey shareKeyFromBase64(String encoded) {
  final bytes = base64Url.decode(base64Url.normalize(encoded));
  return SecretKey(bytes);
}

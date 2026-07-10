/// App-wide encryption service singleton (mirrors the `api` singleton).
///
/// Holds the device key in the OS keystore and talks to /api/encryption over
/// the shared ApiClient. Unlocked after login (see AuthNotifier); the
/// memory/journal CRUD paths call `encryption.protect` / `encryption.reveal`.
library;

import '../api/client.dart';
import 'device_key_store.dart';
import 'encryption_api_http.dart';
import 'encryption_service.dart';

final EncryptionService encryption = EncryptionService(
  SecureStorageDeviceKeyStore(FlutterSecureKvStore()),
  HttpEncryptionApi(api),
);

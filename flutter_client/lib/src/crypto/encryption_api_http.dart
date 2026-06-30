/// HTTP binding of [EncryptionApi] over the shared [ApiClient] (issue #26).
/// Maps the /api/encryption/* JSON shapes to the service's types.
library;

import '../api/client.dart';
import 'encryption_service.dart';

class HttpEncryptionApi implements EncryptionApi {
  final ApiClient _api;
  HttpEncryptionApi(this._api);

  @override
  Future<void> enable(Map<String, dynamic> payload) =>
      _api.post('/api/encryption/enable', payload);

  @override
  Future<EncryptionStatus> fetchStatus(String? devicePublicKeyB64) async {
    final query = devicePublicKeyB64 == null
        ? ''
        : '?device_public_key=${Uri.encodeQueryComponent(devicePublicKeyB64)}';
    final json = await _api.get('/api/encryption/status$query') as Map<String, dynamic>;
    final device = json['device'] as Map<String, dynamic>;
    return EncryptionStatus(
      enabled: json['enabled'] as bool,
      recoveryMethods: (json['recovery_methods'] as List).cast<String>(),
      deviceRegistered: device['registered'] as bool,
      deviceApproved: device['approved'] as bool,
      wrappedCmkB64: device['wrapped_cmk'] as String?,
      ephemeralPublicKeyB64: device['ephemeral_public_key'] as String?,
    );
  }

  @override
  Future<void> registerDevice(String publicKeyB64, String label) =>
      _api.post('/api/encryption/devices/register',
          {'public_key': publicKeyB64, 'label': label});

  @override
  Future<List<PendingDevice>> pendingDevices() async {
    final list = await _api.get('/api/encryption/devices/pending') as List;
    return list
        .map((e) => PendingDevice(
            e['public_key'] as String, e['label'] as String? ?? ''))
        .toList();
  }

  @override
  Future<void> approveDevice(String publicKeyB64, String wrappedCmkB64,
          String ephemeralPublicKeyB64) =>
      _api.post('/api/encryption/devices/approve', {
        'public_key': publicKeyB64,
        'wrapped_cmk': wrappedCmkB64,
        'ephemeral_public_key': ephemeralPublicKeyB64,
      });

  @override
  Future<RecoveryWrapData?> fetchRecoveryWrap(String method) async {
    try {
      final json = await _api.get('/api/encryption/recovery/$method')
          as Map<String, dynamic>;
      return RecoveryWrapData(
        json['wrapped_cmk'] as String,
        json['salt'] as String,
        json['kdf_params_json'] as String?,
      );
    } on ApiException catch (e) {
      if (e.statusCode == 404) return null;
      rethrow;
    }
  }
}

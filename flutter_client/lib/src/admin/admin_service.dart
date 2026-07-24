/// Admin dashboard service — wraps /api/admin/* endpoints.
library;

import '../api/client.dart';

class AdminService {
  /// Dashboard metrics: `{totals: {...}, users: [ {...} ]}`.
  Future<Map<String, dynamic>> getStats() async =>
      await api.get('/api/admin/stats') as Map<String, dynamic>;

  /// Force a storage-cache recompute; the next getStats re-walks the filesystem.
  Future<void> refreshStorage() async =>
      await api.get('/api/admin/storage/refresh');

  /// Search users by email / username / display name (case-insensitive).
  Future<List<Map<String, dynamic>>> searchUsers(String query,
      {int limit = 50}) async {
    final q = Uri.encodeQueryComponent(query);
    final data = await api.get('/api/admin/users/search?q=$q&limit=$limit')
        as List<dynamic>;
    return data.cast<Map<String, dynamic>>();
  }

  /// Reset a user's password. Returns the one-time temp password on success.
  /// Throws [ApiException] (409) when the account's encryption tier forbids it.
  Future<String> resetPassword(int userInfoId) async {
    final data = await api.post(
        '/api/admin/users/$userInfoId/reset-password', {}) as Map<String, dynamic>;
    return data['temp_password'] as String;
  }

  /// Grant or revoke admin access for a user.
  /// Throws [ApiException] (409) when revoking your own admin access.
  Future<void> setAdmin(int userInfoId, bool isAdmin) async {
    await api.post('/api/admin/users/$userInfoId/set-admin', {'is_admin': isAdmin});
  }

  /// Permanently delete a user and all their data.
  /// Throws [ApiException] (409) when deleting your own account this way.
  Future<void> deleteUser(int userInfoId) async {
    await api.delete('/api/admin/users/$userInfoId');
  }

  /// Send a plain-text email to the given users, or to every user when
  /// [sendToAll] is true (in which case [userIds] is ignored). Returns the
  /// number of recipients the email was queued for.
  Future<int> broadcastEmail({
    required String subject,
    required String body,
    List<int> userIds = const [],
    bool sendToAll = false,
  }) async {
    final data = await api.post('/api/admin/broadcast-email', {
      'subject': subject,
      'body': body,
      'user_ids': userIds,
      'send_to_all': sendToAll,
    }) as Map<String, dynamic>;
    return data['sent_count'] as int;
  }
}

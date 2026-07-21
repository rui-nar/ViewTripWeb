/// Generates and uploads per-share encrypted memory content (issue #28).
///
/// Client-side by necessity (the server never sees plaintext or the share
/// key). Explicit, one-shot, owner-triggered — NOT auto-synced on edits;
/// calling [generate] again picks a brand-new key and overwrites the
/// previous envelopes (idempotent regeneration), so a previously copied link
/// stops decrypting and the owner must re-share the freshly generated URL.
///
/// Constructor-injected [ApiClient], mirroring [EncryptionMigration]'s style,
/// so this is unit-testable with a MockClient rather than the app's global
/// `api` singleton.
library;

import '../api/client.dart';
import '../core/project_ref.dart';
import '../crypto/e2ee_crypto.dart' show EncryptedField;
import '../crypto/share_crypto.dart';

class ShareContentGenerator {
  final ApiClient _api;
  ShareContentGenerator(this._api);

  /// Encrypts every actually-encrypted memory in project [ref] under
  /// a fresh share key and PUTs the envelopes to the share/content endpoint.
  ///
  /// [decryptedItems] is the caller's already-decrypted `items` list (e.g.
  /// `ProjectNotifier.items`, revealed in place by `_revealItems`) — needed
  /// because the raw project fetched here still holds ciphertext, so it alone
  /// can't supply the plaintext to re-encrypt under the new share key (same
  /// idiom as [EncryptionMigration.run]).
  ///
  /// Returns the base64 share key to embed in the share URL as `#key=...`,
  /// or null if the project has no encrypted memories to include. Requires a
  /// "full" share token to already exist — content only ever attaches to it.
  Future<String?> generate(
    ProjectRef ref,
    List<Map<String, dynamic>> decryptedItems,
  ) async {
    final raw = await _api.get(ref.path()) as Map<String, dynamic>;
    final rawItems = (raw['items'] as List?) ?? const [];

    final key = await generateShareKey();
    final uploads = <Map<String, dynamic>>[];

    for (final rawEntry in rawItems) {
      if (rawEntry is! Map || rawEntry['item_type'] != 'memory') continue;
      final rawMem = rawEntry['memory'];
      if (rawMem is! Map) continue;
      final rawName = rawMem['name'] as String?;
      final rawDesc = rawMem['description'] as String?;
      final nameEncrypted = rawName != null && EncryptedField.isEnvelope(rawName);
      final descEncrypted = rawDesc != null && EncryptedField.isEnvelope(rawDesc);
      if (!nameEncrypted && !descEncrypted) continue;

      final memId = rawMem['id'];
      final decrypted = decryptedItems.firstWhere(
        (it) =>
            it['item_type'] == 'memory' &&
            (it['memory'] as Map?)?['id'] == memId,
        orElse: () => const <String, dynamic>{},
      );
      final decryptedMem = decrypted['memory'] as Map?;
      if (decryptedMem == null) continue;

      final upload = <String, dynamic>{'memory_id': memId};
      if (nameEncrypted) {
        final plain = decryptedMem['name'] as String?;
        if (plain != null) {
          upload['name_ciphertext'] = await encryptTextWithKey(plain, key);
        }
      }
      if (descEncrypted) {
        final plain = decryptedMem['description'] as String?;
        if (plain != null) {
          upload['description_ciphertext'] = await encryptTextWithKey(plain, key);
        }
      }
      if (upload.length > 1) uploads.add(upload);
    }

    if (uploads.isEmpty) return null;

    await _api.put(
      ref.path('/share/content'),
      {'items': uploads},
    );
    return shareKeyToBase64(key);
  }
}

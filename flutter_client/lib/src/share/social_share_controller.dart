/// Orchestrates a social share end-to-end.
///
/// Plain Dart — no Flutter widgets. All side-effecting boundaries are injected
/// as interfaces ([ShareAssetSource], [ShareLinkResolver], [ShareTransport],
/// [ShareCapabilities]) so the whole flow is unit-testable with fakes.
library;

import 'package:share_plus/share_plus.dart';

import 'share_interfaces.dart';
import 'share_strategy.dart';
import 'social_post_composer.dart';

class SocialShareController {
  final ShareAssetSource assets;
  final ShareLinkResolver links;
  final ShareTransport transport;
  final ShareCapabilities caps;

  const SocialShareController({
    required this.assets,
    required this.links,
    required this.transport,
    required this.caps,
  });

  Future<void> share({
    required ShareTarget target,
    required int memoryId, // internal PK — owner-side photo fetch only
    required String memoryPublicId, // stable UUID — the durable public link
    required String? memoryDate,
    required String customText,
    required bool includeLink,
    required bool includeMap,
    required bool dayFocus,
    required List<String> selectedPhotoUuids,
  }) async {
    // Copy link always needs the link, even when the user disabled it for posts.
    final wantLink = includeLink || target == ShareTarget.copyLink;
    final link =
        wantLink ? await links.resolveMemoryLink(memoryPublicId) : null;

    final post = SocialPostComposer.compose(
      customText: customText,
      includeLink: includeLink,
      link: link,
      selectedPhotoUuids: selectedPhotoUuids,
      includeMap: includeMap,
    );

    final method = ShareStrategy.resolve(target, caps);

    // Copy link: put the bare deep link on the clipboard (fall back to the
    // post text if no token could be resolved). Never fetches assets.
    if (method == ShareMethod.clipboard) {
      return transport.copyToClipboard(link ?? post.text);
    }

    // URL intents carry text + link only — never fetch assets.
    if (method == ShareMethod.urlIntent) {
      return transport.shareUrlIntent(_buildIntentUri(target, post));
    }

    // Sheet paths: gather files (map first, then photos).
    final files = <XFile>[];
    if (post.includeMap) {
      final png =
          await assets.renderMapImage(dayFocus: dayFocus, date: memoryDate);
      if (png != null) {
        files.add(XFile.fromData(png, mimeType: 'image/png', name: 'trip.png'));
      }
    }
    final photos = await assets.fetchPhotos(memoryId, post.photoUuids);
    for (var i = 0; i < photos.length; i++) {
      files.add(
        XFile.fromData(photos[i], mimeType: 'image/jpeg', name: 'photo_$i.jpg'),
      );
    }

    if (method == ShareMethod.sheetWithFiles && files.isNotEmpty) {
      return transport.shareFiles(files, text: post.text);
    }
    // No file-share capability (e.g. desktop web) — degrade to text+link.
    return transport.shareTextOnly(post.text);
  }

  Uri _buildIntentUri(ShareTarget target, ComposedPost post) {
    switch (target) {
      case ShareTarget.whatsapp:
        return Uri.parse('https://wa.me/?text=${_enc(post.text)}');
      case ShareTarget.facebook:
        final u = post.link ?? '';
        return Uri.parse(
          'https://www.facebook.com/sharer/sharer.php'
          '?u=${_enc(u)}&quote=${_enc(post.text)}',
        );
      case ShareTarget.system:
      case ShareTarget.copyLink:
        // These targets never resolve to a URL intent.
        throw ArgumentError('$target is not a URL intent');
    }
  }

  static String _enc(String s) => Uri.encodeComponent(s);
}

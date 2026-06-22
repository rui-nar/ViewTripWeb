/// Injected platform-edge interfaces for social sharing.
///
/// These abstract the side-effecting boundaries (byte rendering, network I/O,
/// token resolution, the actual hand-off, and feature detection) so the
/// orchestrator [SocialShareController] stays pure and fully testable with
/// fakes. Production implementations live alongside in `*_impl.dart`.
library;

import 'dart:typed_data';

import 'package:share_plus/share_plus.dart';

/// Probes whether the current platform can share *files* through the OS sheet.
///
/// Native: always true. Web: true only when the browser supports the Web Share
/// API with files (mobile browsers yes; desktop Chrome generally no).
abstract class ShareCapabilities {
  bool get canShareFiles;
}

/// Produces the binary assets to attach to a post.
abstract class ShareAssetSource {
  /// Renders the trip map as a PNG. [dayFocus] zooms to [date]'s route when set.
  /// Returns null if rendering is unavailable on this platform.
  Future<Uint8List?> renderMapImage({required bool dayFocus, String? date});

  /// Fetches full-res bytes for the given memory photo [uuids].
  Future<List<Uint8List>> fetchPhotos(int memoryId, List<String> uuids);
}

/// Resolves the durable public deep link for a memory, ensuring a share token
/// exists. Returns null if the user disabled the link or no token is available.
abstract class ShareLinkResolver {
  Future<String?> resolveMemoryLink(String memoryPublicId);
}

/// Performs the actual hand-off to the OS / a target platform.
abstract class ShareTransport {
  Future<void> shareFiles(List<XFile> files, {required String text});
  Future<void> shareTextOnly(String text);
  Future<void> shareUrlIntent(Uri uri);
  Future<void> copyToClipboard(String text);
}

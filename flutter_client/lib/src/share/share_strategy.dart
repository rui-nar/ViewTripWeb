/// Pure transport-selection logic for social sharing.
///
/// Decides *how* a post is dispatched given the chosen target and the platform
/// capabilities. No Flutter, no platform — fully unit-testable.
library;

import 'share_interfaces.dart';

/// Where the user wants the post to go.
///
/// Only [system] can carry image files (via the OS share sheet). [whatsapp]
/// and [facebook] are text+link URL intents — no images, by platform design.
/// Instagram is intentionally absent: it has no URL intent and is only
/// reachable through the system sheet.
enum ShareTarget { system, whatsapp, facebook }

/// The concrete dispatch method resolved from a target + capabilities.
enum ShareMethod {
  /// OS share sheet with attached files (map + photos) and text.
  sheetWithFiles,

  /// OS share sheet with text only (e.g. desktop web without file support).
  sheetTextOnly,

  /// Open a platform URL intent carrying text + link only.
  urlIntent,
}

class ShareStrategy {
  const ShareStrategy._();

  static ShareMethod resolve(ShareTarget target, ShareCapabilities caps) =>
      switch (target) {
        ShareTarget.system => caps.canShareFiles
            ? ShareMethod.sheetWithFiles
            : ShareMethod.sheetTextOnly,
        ShareTarget.whatsapp || ShareTarget.facebook => ShareMethod.urlIntent,
      };
}

/// Production [ShareLinkResolver] — ensures a memory-bearing share token
/// exists, then builds the durable deep link `/share/<token>?memory=<publicId>`.
library;

import '../projects/project_notifier.dart';
import 'share_interfaces.dart';

class ShareLinkResolverImpl implements ShareLinkResolver {
  final ProjectNotifier notifier;
  const ShareLinkResolverImpl(this.notifier);

  @override
  Future<String?> resolveMemoryLink(String memoryPublicId) async {
    // Ensure the memory-bearing token exists (never the no-memories token).
    if (notifier.shareToken == null) {
      await notifier.createShareToken();
    }
    final token = notifier.shareToken;
    if (token == null) return null;

    // Same origin pattern used elsewhere: empty baseUrl → current web origin.
    final base =
        notifier.apiBaseUrl.isEmpty ? Uri.base.origin : notifier.apiBaseUrl;
    return '$base/share/$token?memory=$memoryPublicId';
  }
}

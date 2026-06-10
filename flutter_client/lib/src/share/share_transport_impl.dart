/// Production [ShareTransport] — share_plus for the OS sheet, url_launcher for
/// platform URL intents.
library;

import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import 'share_interfaces.dart';

class ShareTransportImpl implements ShareTransport {
  const ShareTransportImpl();

  @override
  Future<void> shareFiles(List<XFile> files, {required String text}) =>
      Share.shareXFiles(files, text: text);

  @override
  Future<void> shareTextOnly(String text) => Share.share(text);

  @override
  Future<void> shareUrlIntent(Uri uri) =>
      launchUrl(uri, mode: LaunchMode.externalApplication);
}

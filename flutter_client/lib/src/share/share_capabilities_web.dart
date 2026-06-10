/// Web [ShareCapabilities] — probes the Web Share API level 2 for file
/// support. Desktop Chrome typically returns false; mobile browsers true.
library;

import 'dart:js_interop';

import 'package:web/web.dart' as web;

import 'share_interfaces.dart';

class _WebShareCapabilities implements ShareCapabilities {
  @override
  bool get canShareFiles {
    try {
      final file = web.File(
        ['x'.toJS].toJS,
        'probe.txt',
        web.FilePropertyBag(type: 'text/plain'),
      );
      final data = web.ShareData(files: [file].toJS);
      return web.window.navigator.canShare(data);
    } catch (_) {
      return false;
    }
  }
}

ShareCapabilities createShareCapabilitiesImpl() => _WebShareCapabilities();

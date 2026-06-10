/// Platform-appropriate [ShareCapabilities] factory.
///
/// Native always supports file sharing; web depends on the Web Share API
/// level 2 (`navigator.canShare` with files). The conditional import keeps
/// `dart:js_interop` / `package:web` out of native builds.
library;

import 'share_interfaces.dart';
import 'share_capabilities_stub.dart'
    if (dart.library.js_interop) 'share_capabilities_web.dart';

ShareCapabilities createShareCapabilities() => createShareCapabilitiesImpl();

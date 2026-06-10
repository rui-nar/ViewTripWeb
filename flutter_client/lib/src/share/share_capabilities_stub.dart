/// Native [ShareCapabilities] — file sharing is always available via the OS
/// share sheet.
library;

import 'share_interfaces.dart';

class _NativeShareCapabilities implements ShareCapabilities {
  @override
  bool get canShareFiles => true;
}

ShareCapabilities createShareCapabilitiesImpl() => _NativeShareCapabilities();

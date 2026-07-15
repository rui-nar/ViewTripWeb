import 'dart:typed_data' show Uint8List;

/// Non-web fallback: there is no page to trigger a browser download from
/// (mobile/desktop apps don't do this), so this is a no-op.
void triggerBrowserDownload(Uint8List bytes, String mimeType, String filename) {}

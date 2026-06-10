/// Cross-platform entry point for downloading PNG bytes as a file.
///
/// On web this triggers a browser blob download; on other platforms it is a
/// no-op (saving to disk goes through a different flow). The conditional
/// import keeps `dart:js_interop` / `package:web` out of the shared codebase
/// so callers compile on mobile.
library;

import 'dart:typed_data';

import 'image_download_stub.dart'
    if (dart.library.js_interop) 'image_download_web.dart';

/// Saves [bytes] as a PNG named [filename]. Web-only; no-op elsewhere.
void downloadPng(Uint8List bytes, String filename) =>
    downloadPngImpl(bytes, filename);

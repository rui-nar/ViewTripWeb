/// Non-web fallback for [downloadPng] — no browser download available.
library;

import 'dart:typed_data';

void downloadPngImpl(Uint8List bytes, String filename) {
  // No-op on native platforms; file persistence is handled elsewhere.
}

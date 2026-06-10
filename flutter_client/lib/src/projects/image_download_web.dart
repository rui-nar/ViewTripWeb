/// Web implementation of [downloadPng] — triggers a browser blob download.
library;

import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

void downloadPngImpl(Uint8List bytes, String filename) {
  final blob = web.Blob(
    [bytes.toJS as JSAny].toJS,
    web.BlobPropertyBag(type: 'image/png'),
  );
  final url = web.URL.createObjectURL(blob);
  (web.document.createElement('a') as web.HTMLAnchorElement)
    ..href = url
    ..download = filename
    ..click();
  web.URL.revokeObjectURL(url);
}

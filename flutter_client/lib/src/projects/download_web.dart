// This file is only ever compiled for web (conditional import), so dart:html is
// the right tool here.
// ignore_for_file: deprecated_member_use, avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'dart:typed_data' show Uint8List;

/// Triggers a browser file download for [bytes] as [filename] with the given
/// [mimeType] (blob URL + a click on a hidden anchor element).
void triggerBrowserDownload(Uint8List bytes, String mimeType, String filename) {
  final blob = html.Blob([bytes], mimeType);
  final url = html.Url.createObjectUrlFromBlob(blob);
  html.AnchorElement(href: url)
    ..setAttribute('download', filename)
    ..click();
  html.Url.revokeObjectUrl(url);
}

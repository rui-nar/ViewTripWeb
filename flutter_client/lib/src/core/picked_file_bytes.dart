/// Reads the bytes of a file returned by the picker without turning an
/// unreadable file into a crash.
///
/// file_picker 11 pre-loaded bytes and reported `null` when that failed; every
/// call site treated null as "skip this file". Version 12 reads lazily via
/// [PlatformFile.readAsBytes], which is non-nullable and throws instead — so
/// the same condition (a file deleted between pick and read, a revoked
/// permission, a dropped blob on web) would escape as an unhandled exception
/// out of a picker callback. This keeps the original null-means-skip shape.
library;

import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';

extension PickedFileBytes on PlatformFile {
  /// The file's bytes, or null if it could not be read.
  Future<Uint8List?> readAsBytesOrNull() async {
    try {
      return await readAsBytes();
    } on Exception {
      return null;
    }
  }
}

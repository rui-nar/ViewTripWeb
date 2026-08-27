/// Tests for GpxImportDialog — the self-contained modal (no OAuth round-trip,
/// unlike Strava/Polarsteps) that lets a user import activities from a
/// single .gpx file.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:cross_file/cross_file.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/gpx_import_dialog.dart';

const _ref = ProjectRef(name: 'Trip');

final Uint8List _gpxBytes = utf8.encode('<gpx></gpx>');

/// Fakes the file_picker plugin so tests can pick a .gpx file without a real
/// platform channel — mirrors memory_dialog_save_result_test.dart's fake.
class _FakeFilePickerPlatform extends FilePickerPlatform {
  _FakeFilePickerPlatform(this.filesToReturn);
  final List<PlatformFile> Function() filesToReturn;

  @override
  Future<List<PlatformFile>> pickFiles({
    String? dialogTitle,
    String? initialDirectory,
    FileType type = FileType.any,
    List<String>? allowedExtensions,
    Function(FilePickerStatus)? onFileLoading,
    int compressionQuality = 0,
    AndroidOptions androidOptions = const AndroidOptions(),
    WindowsOptions windowsOptions = const WindowsOptions(),
    LinuxOptions linuxOptions = const LinuxOptions(),
    WebOptions webOptions = const WebOptions(),
  }) async =>
      filesToReturn();

  @override
  Future<PlatformFile?> pickFile({
    String? dialogTitle,
    String? initialDirectory,
    FileType type = FileType.any,
    List<String>? allowedExtensions,
    Function(FilePickerStatus)? onFileLoading,
    int compressionQuality = 0,
    AndroidOptions androidOptions = const AndroidOptions(),
    WindowsOptions windowsOptions = const WindowsOptions(),
    LinuxOptions linuxOptions = const LinuxOptions(),
    WebOptions webOptions = const WebOptions(),
  }) async {
    final files = filesToReturn();
    return files.isEmpty ? null : files.first;
  }
}

/// file_picker 12 made [PlatformFile] abstract and moved the bytes behind
/// readAsBytes(), so tests supply their own in-memory file rather than
/// constructing one from a byte list.
final class _FakePlatformFile extends PlatformFile {
  _FakePlatformFile({required this.name, required this.bytes});

  @override
  final String name;

  final Uint8List bytes;

  @override
  Uri get uri => Uri.dataFromBytes(bytes);

  @override
  XFile get xFile => XFile.fromData(bytes, name: name);

  @override
  Future<int> length() async => bytes.length;

  @override
  Future<Uint8List> readAsBytes() async => bytes;

  @override
  Stream<Uint8List> readAsByteStream() => Stream.value(bytes);
}

// Opens GpxImportDialog via a real showDialog(), like the app does. The
// MediaQuery override forces 24h time entry (no AM/PM selector) so the time
// picker's input-mode text fields are deterministic to drive in a test.
Widget _harness({http.Client? httpClient}) => MaterialApp(
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(alwaysUse24HourFormat: true),
        child: child!,
      ),
      home: Scaffold(
        body: Builder(
          builder: (context) => ElevatedButton(
            onPressed: () => showDialog<bool>(
              context: context,
              builder: (_) =>
                  GpxImportDialog(projectRef: _ref, httpClient: httpClient),
            ),
            child: const Text('open'),
          ),
        ),
      ),
    );

Future<void> _pickGpxFile(WidgetTester tester) async {
  FilePickerPlatform.instance = _FakeFilePickerPlatform(
    () => [_FakePlatformFile(name: 'track.gpx', bytes: _gpxBytes)],
  );
  await tester.tap(find.text('Choose .gpx file…'));
  await tester.pumpAndSettle();
}

/// Opens the date picker and accepts the pre-selected date (today) via OK —
/// no need to pick a specific day for these tests.
Future<void> _pickDate(WidgetTester tester) async {
  await tester.tap(find.text('Select date…'));
  await tester.pumpAndSettle();
  await tester.tap(find.widgetWithText(TextButton, 'OK'));
  await tester.pumpAndSettle();
}

/// Opens a time picker (identified by [fieldLabel]), switches it to input
/// mode, types [hour]:[minute], and confirms — deterministic regardless of
/// wall-clock time, unlike accepting the dial's TimeOfDay.now() default.
Future<void> _pickTime(
  WidgetTester tester, {
  required String fieldLabel,
  required String hour,
  required String minute,
}) async {
  await tester.tap(find.text(fieldLabel));
  await tester.pumpAndSettle();
  await tester.tap(find.byIcon(Icons.keyboard_outlined));
  await tester.pumpAndSettle();
  final fields = find.byType(TextFormField);
  await tester.enterText(fields.at(0), hour);
  await tester.enterText(fields.at(1), minute);
  await tester.tap(find.widgetWithText(TextButton, 'OK'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
      'renders file/date/time/type fields, and disables submit until a file is picked',
      (tester) async {
    await tester.pumpWidget(_harness());
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    expect(find.text('Choose .gpx file…'), findsOneWidget);
    expect(find.text('Select date…'), findsOneWidget);
    expect(find.text('Start time *'), findsOneWidget);
    expect(find.text('End time *'), findsOneWidget);
    expect(find.byType(DropdownButtonFormField<String>), findsOneWidget);

    ElevatedButton importButton() =>
        tester.widget<ElevatedButton>(find.widgetWithText(ElevatedButton, 'Import'));
    expect(importButton().onPressed, isNull);

    await _pickGpxFile(tester);
    expect(find.text('track.gpx'), findsOneWidget);
    // Still disabled — date/time not yet picked.
    expect(importButton().onPressed, isNull);
  });

  testWidgets('submitting posts the file and form fields to the import-gpx endpoint',
      (tester) async {
    http.Request? captured;
    final mock = MockClient((req) async {
      captured = req;
      return http.Response(jsonEncode({'activity_id': 42, 'total': 5}), 200);
    });

    await tester.pumpWidget(_harness(httpClient: mock));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    await _pickGpxFile(tester);
    await _pickDate(tester);
    await _pickTime(tester, fieldLabel: 'Start time *', hour: '09', minute: '00');
    await _pickTime(tester, fieldLabel: 'End time *', hour: '10', minute: '30');

    await tester.tap(find.widgetWithText(ElevatedButton, 'Import'));
    await tester.pumpAndSettle();

    // The dialog closed on the 200 response.
    expect(find.byType(AlertDialog), findsNothing);

    expect(captured, isNotNull);
    expect(captured!.method, 'POST');
    expect(captured!.url.path, '/api/projects/Trip/activities/import-gpx');
    expect(captured!.headers['content-type'], contains('multipart/form-data'));
    expect(captured!.body, contains('name="start_time"'));
    expect(captured!.body, contains('09:00'));
    expect(captured!.body, contains('10:30'));
    expect(captured!.body, contains('name="activity_type"'));
    expect(captured!.body, contains('run'));
    expect(captured!.body, contains('filename="track.gpx"'));
  });

  testWidgets('a 422 response renders the server errors list, not a generic message',
      (tester) async {
    final errors = [
      'GPX contains 2 tracks; only a single track is supported.',
      'Track has fewer than 2 points.',
    ];
    final mock = MockClient((req) async => http.Response(
        jsonEncode({
          'detail': {'errors': errors},
        }),
        422));

    await tester.pumpWidget(_harness(httpClient: mock));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    await _pickGpxFile(tester);
    await _pickDate(tester);
    await _pickTime(tester, fieldLabel: 'Start time *', hour: '09', minute: '00');
    await _pickTime(tester, fieldLabel: 'End time *', hour: '10', minute: '30');

    await tester.tap(find.widgetWithText(ElevatedButton, 'Import'));
    await tester.pumpAndSettle();

    // Dialog stays open so the user can see (and fix) the problem.
    expect(find.byType(AlertDialog), findsOneWidget);
    for (final e in errors) {
      expect(find.text(e), findsOneWidget);
    }
    expect(find.textContaining('import failed', findRichText: true), findsNothing);
  });
}

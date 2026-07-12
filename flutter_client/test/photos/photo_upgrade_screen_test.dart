import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/core/design_tokens.dart';
import 'package:viewtrip_client/src/photos/photo_match.dart';
import 'package:viewtrip_client/src/photos/photo_source.dart';
import 'package:viewtrip_client/src/photos/photo_upgrade_screen.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

/// Captures replace-photo calls so the dialog is tested without network
/// (mirrors person_form_dialog_test.dart's/encounter_dialog_test.dart's
/// `_FakeNotifier` pattern).
class _FakeNotifier extends ProjectNotifier {
  _FakeNotifier() : super(ProjectService());

  final List<Map<String, String>> replaceCalls = [];
  String? nextUuid = 'new-uuid';

  @override
  Future<String?> replaceMemoryPhoto(
    String memoryId,
    String oldPhotoUuid,
    Uint8List bytes,
    String filename,
  ) async {
    replaceCalls.add({
      'memoryId': memoryId,
      'oldUuid': oldPhotoUuid,
      'filename': filename,
    });
    return nextUuid;
  }
}

final _day = DateTime.utc(2026, 7, 10, 12, 0);
final _otherDay = DateTime.utc(2026, 6, 1, 12, 0);

const _thumbHighHash = 0x0F; // existing thumbnail for the "looks the same" row
const _clearJpgHash = 0x0D; // distance 1 from _thumbHighHash -> looks the same
const _thumbLowHash = 0x00; // existing thumbnail for the "looks different" row
const _farHash = 0x7FFFFFFFFFFFFFFF; // distance 63 from _thumbLowHash -> flagged

Future<int?> _fakeThumbnailHash(String uuid) async {
  switch (uuid) {
    case 'thumb-high-uuid':
      return _thumbHighHash;
    case 'thumb-low-uuid':
      return _thumbLowHash;
    default:
      return null;
  }
}

final _memory = <String, dynamic>{
  'id': 1,
  'date': '2026-07-10',
  'photos': ['thumb-high-uuid', 'thumb-low-uuid'],
  'lat': null,
  'lon': null,
};

/// Bounded settle: while a pick/compare is running, an indeterminate
/// `CircularProgressIndicator` is showing, so `pumpAndSettle` would hang.
/// Pump a fixed number of frames instead (mirrors encounter_dialog_test.dart).
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

Finder _row(String uuid) => find.byKey(ValueKey('upgrade-row-$uuid'));

BoxDecoration _decorationOf(WidgetTester tester, Finder finder) =>
    (tester.widget<Container>(finder).decoration as BoxDecoration);

Future<_FakeNotifier> _openDialog(
  WidgetTester tester, {
  required Future<PickedPhoto?> Function() pickSinglePhoto,
}) async {
  final notifier = _FakeNotifier();
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: Builder(
        builder: (context) => Center(
          child: ElevatedButton(
            onPressed: () => showPhotoUpgradeDialog(
              context,
              notifier,
              _memory,
              pickSinglePhotoOverride: pickSinglePhoto,
              fetchThumbnailHashOverride: _fakeThumbnailHash,
            ),
            child: const Text('open'),
          ),
        ),
      ),
    ),
  ));

  await tester.tap(find.text('open'));
  await _settle(tester);

  return notifier;
}

Future<void> _selectPictureFor(WidgetTester tester, String uuid) async {
  await tester.tap(find.descendant(
    of: _row(uuid),
    matching: find.widgetWithText(OutlinedButton, 'Select picture'),
  ));
  await _settle(tester);
}

void main() {
  testWidgets('each existing photo shows its own row with a picker button', (tester) async {
    await _openDialog(tester, pickSinglePhoto: () async => null);

    expect(_row('thumb-high-uuid'), findsOneWidget);
    expect(_row('thumb-low-uuid'), findsOneWidget);
    expect(
      find.descendant(of: _row('thumb-high-uuid'), matching: find.text('Select picture')),
      findsOneWidget,
    );
  });

  testWidgets('a closely-matching pick renders un-flagged', (tester) async {
    await _openDialog(
      tester,
      pickSinglePhoto: () async => PickedPhoto(
        bytes: Uint8List.fromList([1]),
        filename: 'clear.jpg',
        candidate: PhotoCandidate(capturedAt: _day, pHash: _clearJpgHash),
      ),
    );

    await _selectPictureFor(tester, 'thumb-high-uuid');

    expect(
      find.descendant(of: _row('thumb-high-uuid'), matching: find.widgetWithText(ElevatedButton, 'Confirm')),
      findsOneWidget,
    );
    final border = _decorationOf(tester, _row('thumb-high-uuid')).border as Border;
    expect(border.top.color, isNot(kWarning));
  });

  testWidgets('a pick that looks visually different is flagged', (tester) async {
    await _openDialog(
      tester,
      pickSinglePhoto: () async => PickedPhoto(
        bytes: Uint8List.fromList([2]),
        filename: 'different.jpg',
        candidate: PhotoCandidate(capturedAt: _day, pHash: _farHash),
      ),
    );

    await _selectPictureFor(tester, 'thumb-low-uuid');

    expect(
      find.descendant(
        of: _row('thumb-low-uuid'),
        matching: find.text('Looks different from the current photo.'),
      ),
      findsOneWidget,
    );
    final border = _decorationOf(tester, _row('thumb-low-uuid')).border as Border;
    expect(border.top.color, kWarning);
  });

  testWidgets('a pick captured on a different day is flagged', (tester) async {
    await _openDialog(
      tester,
      pickSinglePhoto: () async => PickedPhoto(
        bytes: Uint8List.fromList([3]),
        filename: 'other-day.jpg',
        candidate: PhotoCandidate(capturedAt: _otherDay, pHash: _clearJpgHash),
      ),
    );

    await _selectPictureFor(tester, 'thumb-high-uuid');

    expect(
      find.descendant(of: _row('thumb-high-uuid'), matching: find.text("Doesn't look like this day.")),
      findsOneWidget,
    );
  });

  testWidgets('confirming a pick fires the expected replace call', (tester) async {
    final notifier = await _openDialog(
      tester,
      pickSinglePhoto: () async => PickedPhoto(
        bytes: Uint8List.fromList([1]),
        filename: 'clear.jpg',
        candidate: PhotoCandidate(capturedAt: _day, pHash: _clearJpgHash),
      ),
    );

    await _selectPictureFor(tester, 'thumb-high-uuid');

    await tester.tap(find.descendant(
      of: _row('thumb-high-uuid'),
      matching: find.widgetWithText(ElevatedButton, 'Confirm'),
    ));
    await _settle(tester);

    expect(notifier.replaceCalls, hasLength(1));
    expect(notifier.replaceCalls.single['oldUuid'], 'thumb-high-uuid');
    expect(notifier.replaceCalls.single['memoryId'], '1');
    expect(notifier.replaceCalls.single['filename'], 'clear.jpg');

    // Applied rows drop their Confirm/Change buttons in favour of a checkmark.
    expect(
      find.descendant(of: _row('thumb-high-uuid'), matching: find.widgetWithText(ElevatedButton, 'Confirm')),
      findsNothing,
    );
    expect(
      find.descendant(of: _row('thumb-high-uuid'), matching: find.byIcon(Icons.check_circle)),
      findsOneWidget,
    );
  });

  testWidgets('cancelling the picker leaves the row untouched', (tester) async {
    await _openDialog(tester, pickSinglePhoto: () async => null);

    await _selectPictureFor(tester, 'thumb-high-uuid');

    expect(
      find.descendant(of: _row('thumb-high-uuid'), matching: find.text('Select picture')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: _row('thumb-high-uuid'), matching: find.widgetWithText(ElevatedButton, 'Confirm')),
      findsNothing,
    );
  });
}

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

// Two disjoint bit-pattern groups so the high/low fixtures below can never
// cross-match each other (kept simply-provable rather than relying on
// pairCandidatesWithThumbnails' greedy tie-breaking across groups).
const _thumbHighHash = 0x0F; // existing "high confidence" thumbnail
const _clearJpgHash = 0x0D; // distance 1 from _thumbHighHash -> no rival
const _thumbLowHash = 0xF00000000; // existing "low confidence" thumbnail
const _candAHash = 0xF00000001; // distance 1 from _thumbLowHash
const _candBHash = 0xF00000003; // distance 2 from _thumbLowHash -> rival for candA

List<PickedPhoto> _fakePicked() => [
      PickedPhoto(
        bytes: Uint8List.fromList([1]),
        filename: 'clear.jpg',
        candidate: PhotoCandidate(capturedAt: _day, pHash: _clearJpgHash),
      ),
      PickedPhoto(
        bytes: Uint8List.fromList([2]),
        filename: 'candidate-a.jpg',
        candidate: PhotoCandidate(capturedAt: _day, pHash: _candAHash),
      ),
      PickedPhoto(
        bytes: Uint8List.fromList([3]),
        filename: 'candidate-b.jpg',
        candidate: PhotoCandidate(capturedAt: _day, pHash: _candBHash),
      ),
    ];

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

/// Bounded settle: while matching runs, an indeterminate
/// `CircularProgressIndicator` is showing, so `pumpAndSettle` would hang.
/// Pump a fixed number of frames instead (mirrors encounter_dialog_test.dart).
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

Future<_FakeNotifier> _openDialog(WidgetTester tester) async {
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
              pickPhotosOverride: () async => _fakePicked(),
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

  await tester.tap(find.text('Pick photos'));
  await _settle(tester);

  return notifier;
}

Finder _tile(String uuid) => find.byKey(ValueKey('swap-tile-$uuid'));

BoxDecoration _decorationOf(WidgetTester tester, Finder finder) =>
    (tester.widget<Container>(finder).decoration as BoxDecoration);

void main() {
  testWidgets('a high-confidence pair renders un-flagged', (tester) async {
    await _openDialog(tester);

    expect(_tile('thumb-high-uuid'), findsOneWidget);
    expect(
      find.descendant(of: _tile('thumb-high-uuid'), matching: find.text('High confidence')),
      findsOneWidget,
    );

    final border = _decorationOf(tester, _tile('thumb-high-uuid')).border as Border;
    expect(border.top.color, isNot(kWarning));
  });

  testWidgets('a low-confidence pair renders visually flagged', (tester) async {
    await _openDialog(tester);

    expect(_tile('thumb-low-uuid'), findsOneWidget);
    expect(
      find.descendant(of: _tile('thumb-low-uuid'), matching: find.text('Low confidence')),
      findsOneWidget,
    );

    final border = _decorationOf(tester, _tile('thumb-low-uuid')).border as Border;
    expect(border.top.color, kWarning);
  });

  testWidgets('confirming a swap fires the expected replace call', (tester) async {
    final notifier = await _openDialog(tester);

    final confirmButton = find.descendant(
      of: _tile('thumb-high-uuid'),
      matching: find.widgetWithText(ElevatedButton, 'Confirm'),
    );
    expect(confirmButton, findsOneWidget);

    await tester.tap(confirmButton);
    await _settle(tester);

    expect(notifier.replaceCalls, hasLength(1));
    expect(notifier.replaceCalls.single['oldUuid'], 'thumb-high-uuid');
    expect(notifier.replaceCalls.single['memoryId'], '1');
    expect(notifier.replaceCalls.single['filename'], 'clear.jpg');

    // Applied rows drop their Confirm/Skip buttons in favour of a checkmark.
    expect(
      find.descendant(of: _tile('thumb-high-uuid'), matching: find.widgetWithText(ElevatedButton, 'Confirm')),
      findsNothing,
    );
    expect(
      find.descendant(of: _tile('thumb-high-uuid'), matching: find.byIcon(Icons.check_circle)),
      findsOneWidget,
    );
  });

  testWidgets('skipping a swap does not fire a replace call', (tester) async {
    final notifier = await _openDialog(tester);

    final skipButton = find.descendant(
      of: _tile('thumb-low-uuid'),
      matching: find.widgetWithText(TextButton, 'Skip'),
    );
    expect(skipButton, findsOneWidget);

    await tester.tap(skipButton);
    await _settle(tester);

    expect(notifier.replaceCalls, isEmpty);
    // A skipped row is hidden from the review list.
    expect(_tile('thumb-low-uuid'), findsNothing);
  });
}

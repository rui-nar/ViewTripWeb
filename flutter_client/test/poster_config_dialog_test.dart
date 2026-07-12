// Widget tests for PosterConfigDialog (mirrors photo_upgrade_screen_test.dart's
// pumpWidget/showDialog/tap style): confirm each checkbox toggles its own
// field and the confirm callback receives the expected options object.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/projects/poster_config_dialog.dart';

const _defaults = PosterConfigOptions(
  distance: true,
  elevation: true,
  heroPhoto: true,
  allPhotos: false,
  memoryText: true,
  counters: true,
  tagPie: false,
  encounters: false,
);

Future<PosterConfigOptions?> _openAndConfirm(
  WidgetTester tester, {
  List<String> toggleTitles = const [],
  bool cancel = false,
}) async {
  PosterConfigOptions? result;
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: Builder(
        builder: (context) => Center(
          child: ElevatedButton(
            onPressed: () => showDialog<void>(
              context: context,
              builder: (_) => PosterConfigDialog(
                onConfirm: (opts) => result = opts,
              ),
            ),
            child: const Text('open'),
          ),
        ),
      ),
    ),
  ));

  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();

  for (final title in toggleTitles) {
    await tester.tap(find.widgetWithText(CheckboxListTile, title));
    await tester.pump();
  }

  await tester.tap(find.text(cancel ? 'Cancel' : 'Generate'));
  await tester.pumpAndSettle();

  return result;
}

void main() {
  testWidgets('confirming with no changes returns the default options',
      (tester) async {
    final result = await _openAndConfirm(tester);

    expect(result, isNotNull);
    expect(result!.toJson(), _defaults.toJson());
  });

  testWidgets('cancel does not invoke the confirm callback', (tester) async {
    final result = await _openAndConfirm(tester, cancel: true);
    expect(result, isNull);
  });

  testWidgets('toggling two checkboxes flips only those fields',
      (tester) async {
    final result = await _openAndConfirm(
      tester,
      toggleTitles: ['All photos', 'Distance'],
    );

    expect(result, isNotNull);
    expect(result!.allPhotos, isTrue); // default false -> toggled on
    expect(result.distance, isFalse); // default true -> toggled off
    // Untouched fields keep their defaults.
    expect(result.elevation, _defaults.elevation);
    expect(result.heroPhoto, _defaults.heroPhoto);
    expect(result.memoryText, _defaults.memoryText);
    expect(result.counters, _defaults.counters);
    expect(result.tagPie, _defaults.tagPie);
    expect(result.encounters, _defaults.encounters);
  });

  // Every checkbox title maps 1:1 to a PosterConfigOptions.toJson() key.
  const fieldsByTitle = {
    'Distance': 'distance',
    'Elevation': 'elevation',
    'Hero photo': 'hero_photo',
    'All photos': 'all_photos',
    'Memory text': 'memory_text',
    'Counters': 'counters',
    'Tag pie chart': 'tag_pie',
    'Number of encounters': 'encounters',
  };

  for (final entry in fieldsByTitle.entries) {
    testWidgets('toggling "${entry.key}" flips only the ${entry.value} field',
        (tester) async {
      final result = await _openAndConfirm(tester, toggleTitles: [entry.key]);
      expect(result, isNotNull);

      final defaultsJson = _defaults.toJson();
      final actualJson = result!.toJson();
      for (final key in defaultsJson.keys) {
        if (key == entry.value) {
          expect(actualJson[key], !defaultsJson[key]!,
              reason: '$key should have flipped');
        } else {
          expect(actualJson[key], defaultsJson[key],
              reason: '$key should be unchanged');
        }
      }
    });
  }
}

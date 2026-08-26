// computeElevationSpots — the concatenate+LTTB-downsample computation
// elevation_chart.dart runs via `compute()` on a background isolate when the
// unfiltered (no activity selected) elevation series is large. See
// elevation_chart.dart's doc comment on computeElevationSpots for why: a
// long trip's full elevation payload, concatenated across every activity,
// can be tens of thousands of points, and doing that synchronously on the
// UI isolate is the same mistake the day-carousel ANR fix corrected
// elsewhere (map_panel.dart's buildDayIndex). This only exercises the pure
// computation itself, same scope as build_day_index_test.dart.

import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/projects/elevation_chart.dart';

void main() {
  Map<String, dynamic> activity(dynamic id, List<List<num>> profile) =>
      {'id': id, 'elevation_profile': profile};

  test('concatenates activities in order, offsetting distance by the '
      'previous activity\'s total', () {
    final result = computeElevationSpots((
      activities: [
        activity(1, [
          [0.0, 100],
          [5.0, 200],
        ]),
        activity(2, [
          [0.0, 150],
          [3.0, 50],
        ]),
      ],
      selectedId: null,
    ));

    expect(result.spots.map((s) => (s.x, s.y)).toList(), [
      (0.0, 100.0),
      (5.0, 200.0),
      (5.0, 150.0), // second activity's 0.0 offset by the first's 5.0 total
      (8.0, 50.0),
    ]);
  });

  test('minY/maxY span the full series, not just the downsampled points', () {
    final result = computeElevationSpots((
      activities: [
        activity(1, [
          [0.0, 10],
          [1.0, -5],
          [2.0, 40],
          [3.0, 0],
        ]),
      ],
      selectedId: null,
    ));
    expect(result.minY, -5);
    expect(result.maxY, 40);
  });

  test('selectedId filters to just that activity', () {
    final result = computeElevationSpots((
      activities: [
        activity(1, [
          [0.0, 100],
          [5.0, 200],
        ]),
        activity(2, [
          [0.0, 999],
          [3.0, 999],
        ]),
      ],
      selectedId: 2,
    ));
    // Not offset by activity 1 — it was filtered out entirely, not just hidden.
    expect(result.spots.map((s) => (s.x, s.y)).toList(), [
      (0.0, 999.0),
      (3.0, 999.0),
    ]);
  });

  test('empty activities yields empty spots and zeroed bounds', () {
    final result = computeElevationSpots((activities: const [], selectedId: null));
    expect(result.spots, isEmpty);
    expect(result.minY, 0);
    expect(result.maxY, 0);
  });

  test('a series over the downsample threshold is capped, keeping the '
      'first and last point', () {
    final profile = List.generate(1000, (i) => [i * 0.1, i.toDouble()]);
    final result = computeElevationSpots((
      activities: [activity(1, profile)],
      selectedId: null,
    ));
    expect(result.spots.length, lessThan(1000));
    expect(result.spots.first.x, 0.0);
    expect(result.spots.last.x, closeTo(99.9, 0.001));
    // Downsampling must not distort the true range.
    expect(result.minY, 0);
    expect(result.maxY, 999);
  });
}

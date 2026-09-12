/// A saved tag, sleeping, activity-type or transport filter that no longer
/// matches anything (#409).
///
/// Filter a trip to hikes, delete the last hike, reload: the saved 'hike'
/// restored verbatim, matched no day and emptied the list, and the filter sheet
/// — which offers what the trip holds — had no 'hike' chip to untick. Only
/// "Clear all" got out, taking every other dimension with it. The source
/// dimension was fixed for this in #406; these pin the same contract for the
/// rest, through the real load() so the write-back and its ordering are covered
/// and not just the pruning seam.
library;

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/project_filters.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

const _ref = ProjectRef(name: 'Trip');
const _key = 'project_ui_state_Trip';
const _day1 = '2026-06-01';
const _day2 = '2026-06-02';

Map<String, dynamic> _emptyGeo() =>
    {'type': 'FeatureCollection', 'features': <dynamic>[]};

/// What the fake server holds, mutable between loads the way editing the trip
/// changes it.
class _Trip {
  final activities = <Map<String, dynamic>>[
    {
      'id': 1,
      'name': 'Morning ride',
      'type': 'Ride',
      'start_date_local': '${_day1}T09:00:00',
    },
  ];
  final segments = <Map<String, dynamic>>[
    {'id': 11, 'segment_type': 'train', 'date': _day1},
  ];
  final dayMeta = <String, Map<String, dynamic>>{
    _day1: {
      'tags': ['beach'],
      'sleeping': 'Hotel',
    },
    // No tags of its own, so it inherits 'beach'; no sleeping mode, so it
    // filters as 'No data'.
    _day2: {},
  };
}

class _Service extends ProjectService {
  _Service(this.trip);

  final _Trip trip;

  Map<String, dynamic> _payload() => {
        'name': 'Trip',
        'activities': [for (final a in trip.activities) {...a}],
        'items': [
          for (final a in trip.activities)
            {'item_type': 'activity', 'activity_id': a['id']},
          for (final s in trip.segments)
            {'item_type': 'segment', 'segment': {...s}},
        ],
        'day_meta': {
          for (final e in trip.dayMeta.entries) e.key: {...e.value},
        },
        'people': <dynamic>[],
        'groups': <dynamic>[],
      };

  @override
  Future<Map<String, dynamic>> getDetailsMeta(ProjectRef ref) async =>
      _payload();

  @override
  Future<Map<String, dynamic>> getDetails(ProjectRef ref,
          {bool bypassCache = false}) async =>
      _payload();

  @override
  Future<Map<String, dynamic>> getLowResGeo(ProjectRef ref) async =>
      _emptyGeo();

  @override
  Future<Map<String, dynamic>> getGeo(ProjectRef ref,
          {bool bypassCache = false}) async =>
      _emptyGeo();
}

/// One filter dimension: a value the trip holds, one it does not, and how the
/// trip comes to hold the stale one again.
class _Dimension {
  const _Dimension({
    required this.name,
    required this.key,
    required this.held,
    required this.stale,
    required this.read,
    required this.regain,
  });

  final String name;
  final String key; // as _saveUiState writes it
  final String held;
  final String stale;
  final Set<String> Function(ProjectNotifier) read;
  final void Function(_Trip) regain;
}

final _dimensions = [
  _Dimension(
    name: 'activity type',
    key: 'activityTypes',
    held: 'ride',
    stale: 'hike',
    read: (n) => n.activityTypeFilter,
    // Capitalised as the server sends it; the filter matches lower-cased.
    regain: (t) => t.activities.add({
      'id': 2,
      'name': 'Afternoon hike',
      'type': 'Hike',
      'start_date_local': '${_day2}T14:00:00',
    }),
  ),
  _Dimension(
    name: 'transport',
    key: 'transport',
    held: 'train',
    stale: 'flight',
    read: (n) => n.transportFilter,
    regain: (t) =>
        t.segments.add({'id': 12, 'segment_type': 'flight', 'date': _day2}),
  ),
  _Dimension(
    name: 'tag',
    key: 'tags',
    held: 'beach',
    stale: 'museum',
    read: (n) => n.tagFilter,
    regain: (t) => t.dayMeta[_day2] = {
      'tags': ['museum'],
    },
  ),
  _Dimension(
    name: 'sleeping mode',
    key: 'sleeping',
    held: 'Hotel',
    stale: 'Camping',
    read: (n) => n.sleepingFilter,
    regain: (t) => t.dayMeta[_day2] = {'sleeping': 'Camping'},
  ),
];

Future<Map<String, dynamic>> _stored() async {
  final prefs = await SharedPreferences.getInstance();
  return jsonDecode(prefs.getString(_key)!) as Map<String, dynamic>;
}

Future<ProjectNotifier> _loaded(_Service service) async {
  final notifier = ProjectNotifier(service);
  await notifier.load(_ref);
  await pumpEventQueue();
  return notifier;
}

void main() {
  for (final d in _dimensions) {
    group('a saved ${d.name} filter', () {
      test('drops the value the trip no longer holds, in memory and on disk',
          () async {
        // The fixture carries a selection too. load() nulls the selection
        // fields before fetching and _saveUiState builds its payload
        // synchronously, so a write-back fired before the selection restores
        // would persist those nulls over the user's day and activity.
        SharedPreferences.setMockInitialValues({
          _key: jsonEncode({
            d.key: [d.stale, d.held],
            'selectedDay': _day1,
            'selectedActivityId': '1',
          }),
        });
        final service = _Service(_Trip());

        final notifier = await _loaded(service);

        expect(d.read(notifier), {d.held});
        expect(notifier.selectedDays, isNotEmpty,
            reason: 'the value the trip still holds keeps narrowing');
        expect(notifier.selectedDay, _day1);
        expect(notifier.selectedActivityId, '1');

        final stored = await _stored();
        expect(stored[d.key], [d.held],
            reason: 'a value dropped in memory only comes back with the data');
        expect(stored['selectedDay'], _day1,
            reason: 'pruning a filter must not cost the user their selection');
        expect(stored['selectedActivityId'], '1');

        // And the next open of the trip still has the selection.
        final next = await _loaded(service);
        expect(next.selectedDay, _day1);
        expect(next.selectedActivityId, '1');
        expect(d.read(next), {d.held});
      });

      test('does not re-apply itself when the trip regains matching data',
          () async {
        SharedPreferences.setMockInitialValues({
          _key: jsonEncode({
            d.key: [d.stale],
          }),
        });
        final service = _Service(_Trip());
        final notifier = await _loaded(service);
        expect(notifier.hasActiveFilter, isFalse);

        d.regain(service.trip);
        await notifier.load(_ref);
        await pumpEventQueue();

        expect(d.read(notifier), isEmpty,
            reason: 'the user never re-ticked it');
        expect(notifier.hasActiveFilter, isFalse);
      });

      test('keeps a value the trip still holds, and leaves storage alone',
          () async {
        final saved = jsonEncode({
          d.key: [d.held],
          'selectedDay': _day1,
        });
        SharedPreferences.setMockInitialValues({_key: saved});

        final notifier = await _loaded(_Service(_Trip()));

        expect(d.read(notifier), {d.held});
        expect(notifier.selectedDays, isNotEmpty);
        final prefs = await SharedPreferences.getInstance();
        expect(prefs.getString(_key), saved);
      });
    });
  }

  test('every dimension is pruned in the same load, and one write keeps it',
      () async {
    SharedPreferences.setMockInitialValues({
      _key: jsonEncode({
        for (final d in _dimensions) d.key: [d.stale, d.held],
        'sources': ['gpx', 'strava'],
        'selectedDay': _day1,
      }),
    });

    final notifier = await _loaded(_Service(_Trip()));

    for (final d in _dimensions) {
      expect(d.read(notifier), {d.held}, reason: d.name);
    }
    expect(notifier.sourceFilter, {'strava'});
    expect(notifier.selectedDays, {_day1});
    final stored = await _stored();
    for (final d in _dimensions) {
      expect(stored[d.key], [d.held], reason: d.name);
    }
    expect(stored['sources'], ['strava']);
    expect(stored['selectedDay'], _day1);
  });

  group('tags prune against availableTags, and that is safe', () {
    // Tags match on *effective* tags (issue #18): a day with none of its own
    // inherits the nearest earlier day's, and an explicit empty set stops that
    // (#203). availableTags is only the tags days own, so pruning against it
    // would be wrong if any day could match a tag nobody owns. None can: an
    // inherited tag is some earlier day's own tag, and a day's own tags are its
    // effective tags. These pin that, so a change to either side is noticed.
    ProjectNotifier notifierWith(Map<String, Map<String, dynamic>> dayMeta) =>
        ProjectNotifier(ProjectService())..dayMeta = dayMeta;

    final dayMeta = <String, Map<String, dynamic>>{
      '2026-06-01': {
        'tags': ['beach', 'city'],
      },
      '2026-06-02': {}, // inherits beach, city
      '2026-06-03': {'tags': <String>[]}, // cleared: inherits nothing
      '2026-06-04': {}, // skips the cleared day, inherits beach, city
      '2026-06-05': {
        'tags': ['museum'],
      },
      '2026-06-06': {}, // inherits museum
    };

    test('the effective tags across the trip are exactly availableTags', () {
      final notifier = notifierWith(dayMeta);

      final effective =
          dayMeta.keys.expand(notifier.effectiveTagsFor).toSet();

      expect(effective, notifier.availableTags.toSet());
    });

    test('restore keeps a tag if and only if it matches a day', () {
      for (final tag in ['beach', 'city', 'museum', 'hiking']) {
        final probe = notifierWith(dayMeta)..setFilters(tags: {tag});
        final matches = probe.selectedDays.isNotEmpty;

        final notifier = notifierWith(dayMeta);
        final pruned = notifier.restoreFilters(ProjectFilters(tags: {tag}));

        expect(notifier.tagFilter.contains(tag), matches, reason: tag);
        expect(pruned, !matches, reason: tag);
        expect(notifier.selectedDays, probe.selectedDays, reason: tag);
      }
    });
  });
}

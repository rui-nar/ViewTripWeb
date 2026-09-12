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
import 'package:viewtrip_client/src/projects/project_data_cache.dart';
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
  _Service(this.trip, {this.name = 'Trip', this.callerRole});

  final _Trip trip;
  final String name;

  /// What the server says the caller is on this trip. It always sends one;
  /// null here leaves the ref's own role standing.
  final String? callerRole;

  /// Every fetch fails, the way it does with no network.
  bool offline = false;

  Map<String, dynamic> _payload() => {
        'name': name,
        'lock_version': 1,
        if (callerRole != null) 'caller_role': callerRole,
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

  Future<T> _answer<T>(T Function() value) async {
    if (offline) throw Exception('offline');
    return value();
  }

  @override
  Future<Map<String, dynamic>> getDetailsMeta(ProjectRef ref) =>
      _answer(_payload);

  @override
  Future<Map<String, dynamic>> getDetails(ProjectRef ref,
          {bool bypassCache = false}) =>
      _answer(_payload);

  @override
  Future<Map<String, dynamic>> getLowResGeo(ProjectRef ref) =>
      _answer(_emptyGeo);

  @override
  Future<Map<String, dynamic>> getGeo(ProjectRef ref,
          {bool bypassCache = false}) =>
      _answer(_emptyGeo);
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

Future<ProjectNotifier> _loaded(_Service service,
    {ProjectRef ref = _ref}) async {
  final notifier = ProjectNotifier(service)
    ..loadRetryBackoff = const [Duration(milliseconds: 1)];
  await notifier.load(ref);
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
  group('a trip shared with you under the name of one of your own', () {
    // Trip names are unique per owner, not globally: a companion's copy of the
    // same holiday is likely to be called the same thing (#106). Keyed by name
    // alone, opening theirs read your saved state, pruned it against their
    // data, and wrote the loss back over your own trip's.
    const mine = ProjectRef(name: 'Japan');
    // As AppScreen passes it: ?owner=7 from the URL, role resolved against the
    // signed-in user, which the server's caller_role then confirms.
    const theirs = ProjectRef(name: 'Japan', ownerId: 7, role: 'editor');
    const ownKey = 'project_ui_state_Japan';
    final ownState = jsonEncode({
      'activityTypes': ['hike'],
      'selectedDay': _day1,
      'selectedActivityId': '2',
    });

    _Service myJapan() => _Service(
        _Trip()
          ..activities.add({
            'id': 2,
            'name': 'Temple hike',
            'type': 'Hike',
            'start_date_local': '${_day1}T14:00:00',
          }),
        name: 'Japan',
        callerRole: 'owner');
    // Theirs has no hikes, so a restore of your state would prune 'hike'.
    _Service theirJapan() =>
        _Service(_Trip(), name: 'Japan', callerRole: 'editor');

    test('opening theirs leaves your saved filter and selection alone',
        () async {
      SharedPreferences.setMockInitialValues({ownKey: ownState});

      final shared = await _loaded(theirJapan(), ref: theirs);
      expect(shared.hasActiveFilter, isFalse,
          reason: 'your filter is not theirs to apply');
      expect(shared.selectedActivityId, isNull);

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(ownKey), ownState);

      final own = await _loaded(myJapan(), ref: mine);
      expect(own.activityTypeFilter, {'hike'});
      expect(own.selectedActivityId, '2');
    });

    test('and theirs keeps state of its own, under its owner', () async {
      SharedPreferences.setMockInitialValues({ownKey: ownState});
      final service = theirJapan();

      final shared = await _loaded(service, ref: theirs);
      shared.setFilters(activityTypes: {'ride'});
      shared.selectActivity(1);
      await pumpEventQueue();

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(ownKey), ownState);
      expect(prefs.getString('project_ui_state_7:Japan'), contains('ride'));

      final again = await _loaded(service, ref: theirs);
      expect(again.activityTypeFilter, {'ride'});
      expect(again.selectedActivityId, '1');
    });

    test('your own trip opened from the projects list is still your own trip',
        () async {
      // The list gives your own entries your id as owner_id, so from there the
      // trip opens as ?owner=<you>; from a deep link it opens without. Both
      // must find the state saved under the key own trips have always used.
      SharedPreferences.setMockInitialValues({ownKey: ownState});

      final own = await _loaded(myJapan(),
          ref: const ProjectRef(name: 'Japan', ownerId: 3));

      expect(own.activityTypeFilter, {'hike'});
      expect(own.selectedActivityId, '2');
    });

    test('state an own trip saved before the key changed still restores',
        () async {
      SharedPreferences.setMockInitialValues({ownKey: ownState});

      final own = await _loaded(myJapan(), ref: mine);

      expect(own.activityTypeFilter, {'hike'});
      expect(own.selectedDay, _day1);
      expect(own.selectedActivityId, '2');
    });
  });

  group('an offline load', () {
    // Offline, the trip is the cached /meta snapshot, which local edits do not
    // refresh. Set a night to Camping, tick the Camping filter, then open the
    // trip with no network: the snapshot predates the Camping night, and
    // pruning against it would delete a filter that is still good.
    setUp(projectDataCache.resetForTest);

    test('keeps a filter the snapshot does not hold, and never saves the loss',
        () async {
      SharedPreferences.setMockInitialValues({
        _key: jsonEncode({
          'sleeping': ['Camping'],
          'selectedDay': _day1,
        }),
      });
      final service = _Service(_Trip()); // the snapshot: no Camping night
      projectDataCache.onMetaFetched(_ref, service._payload());
      service.offline = true;

      final notifier = await _loaded(service);

      expect(notifier.offlineFromCache, isTrue);
      expect(notifier.sleepingFilter, {'Camping'});
      expect((await _stored())['sleeping'], ['Camping']);

      // The next selection change saves whatever is in memory.
      notifier.selectDay(_day2);
      await pumpEventQueue();
      expect((await _stored())['sleeping'], ['Camping'],
          reason: 'a pruned in-memory set would be written here');

      // Back online, where the Camping night is.
      service.offline = false;
      service.trip.dayMeta[_day2] = {'sleeping': 'Camping'};
      await notifier.load(_ref);
      await pumpEventQueue();

      expect(notifier.offlineFromCache, isFalse);
      expect(notifier.sleepingFilter, {'Camping'});
      expect(notifier.selectedDays, {_day2});
    });

    test('and an online load after it still prunes what is really gone',
        () async {
      SharedPreferences.setMockInitialValues({
        _key: jsonEncode({
          'sleeping': ['Camping'],
        }),
      });
      final service = _Service(_Trip());
      projectDataCache.onMetaFetched(_ref, service._payload());
      service.offline = true;
      final notifier = await _loaded(service);
      expect(notifier.sleepingFilter, {'Camping'});

      service.offline = false;
      await notifier.load(_ref);
      await pumpEventQueue();

      expect(notifier.sleepingFilter, isEmpty);
      expect((await _stored())['sleeping'], isEmpty);
    });
  });
}

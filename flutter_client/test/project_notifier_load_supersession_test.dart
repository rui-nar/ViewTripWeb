// Regression tests for issue #283: ProjectNotifier's background loads had no
// real cancellation, just ad hoc `_loadKey != ref` guards. Since ProjectRef.==
// is structural (project_ref.dart), those guards only ever caught navigation
// to a *different* project — a second concurrent load of the *same* ref (e.g.
// the user mashing a Retry button) compared equal and could still let a
// stale background continuation mutate/notify after a newer one had already
// taken over. _loadToken (project_notifier.dart) closes that gap.
//
// These tests deliberately race two same-ref calls against each other via
// Completer-controlled fakes, matching the "manual gen/token" testing
// convention already used by build_full_track_background_isolate_test.dart
// (see that file's header) rather than sleeping and hoping for an ordering —
// the whole point of these bugs is that they're about race *ordering*.

import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/project_data_cache.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

const _ref = ProjectRef(name: 'Trip');

Map<String, dynamic> _meta() => {
      'name': 'Trip',
      'activities': [
        {'id': '1', 'name': 'meta'}
      ],
      'items': [
        {'item_type': 'activity', 'activity_id': '1'}
      ],
      'people': [],
      'groups': [],
    };

Map<String, dynamic> _emptyGeo() => {'type': 'FeatureCollection', 'features': <dynamic>[]};

Map<String, dynamic> _detailsNamed(String name) => {
      'activities': [
        {'id': '1', 'name': name}
      ],
    };

/// A [ProjectService] whose `getGeo`/`getDetails` calls are held open on
/// Completers the test resolves by hand, so two concurrent same-ref
/// `load()` calls can be interleaved deterministically. `getDetailsMeta`/
/// `getLowResGeo` resolve immediately — only the Phase 2 fetches (the ones
/// _loadFullGeoProgressively/_loadElevationData act on) need controlling.
class _RacingService extends ProjectService {
  final List<Completer<Map<String, dynamic>>> geoCalls = [];
  final List<Completer<Map<String, dynamic>>> detailsCalls = [];

  @override
  Future<Map<String, dynamic>> getDetailsMeta(ProjectRef ref) async => _meta();

  @override
  Future<Map<String, dynamic>> getLowResGeo(ProjectRef ref) async => _emptyGeo();

  @override
  Future<Map<String, dynamic>> getGeo(ProjectRef ref, {bool bypassCache = false}) {
    final c = Completer<Map<String, dynamic>>();
    geoCalls.add(c);
    return c.future;
  }

  @override
  Future<Map<String, dynamic>> getDetails(ProjectRef ref, {bool bypassCache = false}) {
    final c = Completer<Map<String, dynamic>>();
    detailsCalls.add(c);
    return c.future;
  }
}

/// Test-only subclass exposing the @protected applyFullActivities/
/// currentLoadToken seam ProjectNotifier gives staged-loading subclasses
/// (ViewProjectNotifier, SharedProjectNotifier) — see view_screen.dart /
/// shared_project_screen.dart for the real callers this mirrors.
class _ExposedNotifier extends ProjectNotifier {
  _ExposedNotifier(super.service);

  Future<void> apply(List<Map<String, dynamic>> acts, {int? token}) =>
      applyFullActivities(acts, token: token);

  int get token => currentLoadToken;
}

Future<void> _pumpUntil(bool Function() done, {int maxTicks = 40}) async {
  for (var i = 0; i < maxTicks && !done(); i++) {
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
}

void main() {
  setUp(() => projectDataCache.resetForTest());

  test(
      '_loadFullGeoProgressively: a stale load()\'s geo fetch resolving late '
      'does not flip isGeoLoaded for a second concurrent load() of the same '
      'ref (issue #283 bug #1, same-ref case)', () async {
    final svc = _RacingService();
    final notifier = ProjectNotifier(svc);

    // isGeoLoaded defaults to true on the base ProjectNotifier ("so
    // manage-mode screens that use the base load() see no behaviour change"
    // — see its doc comment); only ViewProjectNotifier/SharedProjectNotifier
    // reset it false before calling load() to use it progressively. Mirror
    // that here so this test can observe _loadFullGeoProgressively's write to
    // it, exactly as those subclasses do in production.

    // Call A: Phase 1 completes fast; Phase 2's getGeo() is held on
    // geoCalls[0].
    await notifier.load(_ref);
    notifier.isGeoLoaded = false;
    await _pumpUntil(() => svc.geoCalls.length == 1);
    expect(svc.geoCalls, hasLength(1));
    expect(notifier.isGeoLoaded, isFalse);

    // Call B: a second concurrent load() for the *same* ref — the exact
    // "mashing Retry" scenario the issue describes. Its own Phase 2 getGeo()
    // is held on geoCalls[1].
    await notifier.load(_ref);
    notifier.isGeoLoaded = false;
    await _pumpUntil(() => svc.geoCalls.length == 2);
    expect(svc.geoCalls, hasLength(2));
    expect(notifier.isGeoLoaded, isFalse);

    // Resolve A's (stale) fetch first. Before the fix, `_loadKey == ref`
    // still held (same ref!) so this alone used to flip isGeoLoaded even
    // though B — the call actually in flight now — hasn't delivered anything.
    svc.geoCalls[0].complete(_emptyGeo());
    await _pumpUntil(() => false, maxTicks: 5); // let the continuation run
    expect(notifier.isGeoLoaded, isFalse,
        reason: 'a stale same-ref load must not be able to mark geo loaded '
            'for the call that actually superseded it');

    // Now resolve B's (current) fetch — this is the one that should count.
    svc.geoCalls[1].complete(_emptyGeo());
    await _pumpUntil(() => notifier.isGeoLoaded);
    expect(notifier.isGeoLoaded, isTrue);

    // Both geo fetches finishing chains into _loadElevationData's own
    // getDetails() call (via whenComplete) — drain those too so nothing is
    // left hanging past the end of the test.
    await _pumpUntil(() => svc.detailsCalls.length == 2);
    for (final c in svc.detailsCalls) {
      if (!c.isCompleted) c.complete(_detailsNamed('drained'));
    }
    await _pumpUntil(() => false, maxTicks: 5);
  });

  test(
      '_loadElevationData: a stale load()\'s details fetch resolving late '
      'does not overwrite activities merged by a second concurrent load() of '
      'the same ref (issue #283, same-ref case)', () async {
    final svc = _RacingService();
    final notifier = ProjectNotifier(svc);

    // Call A: Phase 2's getGeo() resolves immediately (not under test here);
    // its getDetails() (feeding _loadElevationData) is held on detailsCalls[0].
    await notifier.load(_ref);
    await _pumpUntil(() => svc.geoCalls.isNotEmpty);
    svc.geoCalls[0].complete(_emptyGeo());
    await _pumpUntil(() => svc.detailsCalls.length == 1);
    expect(svc.detailsCalls, hasLength(1));

    // Call B: second concurrent load() for the same ref.
    await notifier.load(_ref);
    await _pumpUntil(() => svc.geoCalls.length == 2);
    svc.geoCalls[1].complete(_emptyGeo());
    await _pumpUntil(() => svc.detailsCalls.length == 2);
    expect(svc.detailsCalls, hasLength(2));

    // B's (current) details land first with the real data.
    svc.detailsCalls[1].complete(_detailsNamed('CURRENT'));
    await _pumpUntil(() => notifier.activities.first['name'] == 'CURRENT');
    expect(notifier.activities.first['name'], 'CURRENT');

    // A's (stale) details land late. Pre-fix, `_loadKey != ref` was the only
    // guard here and — same ref — it wouldn't have caught this: the merge
    // would silently overwrite 'CURRENT' with 'STALE'.
    svc.detailsCalls[0].complete(_detailsNamed('STALE'));
    await _pumpUntil(() => false, maxTicks: 10);
    expect(notifier.activities.first['name'], 'CURRENT',
        reason: 'the stale same-ref load\'s details fetch must not clobber '
            'the current load\'s already-merged activities');
  });

  test(
      'applyFullActivities: rejects a token captured before a load() that '
      'has since been superseded, even for the same ref (issue #283 bug #3)',
      () async {
    // _RacingService (not the default ProjectService(), which would hit the
    // real network via the global `api`) — its Phase 2 fetches are drained at
    // the end below; this test only cares about the token load() bumps.
    final svc = _RacingService();
    final notifier = _ExposedNotifier(svc);
    await notifier.load(_ref);
    notifier.activities = [
      {'id': '1', 'name': 'OLD'}
    ];
    final staleToken = notifier.token;

    // A second concurrent load() for the *same* ref supersedes staleToken —
    // currentLoadKey would still equal the ref (structural equality), so
    // only the token can tell these two calls apart.
    await notifier.load(_ref);
    notifier.activities = [
      {'id': '1', 'name': 'CURRENT'}
    ];

    // Applying with the stale token must be rejected outright — not even the
    // activities merge should run (bug #3: it used to mutate unconditionally
    // and only skip the trailing notify).
    await notifier.apply([
      {'id': '1', 'name': 'STALE'}
    ], token: staleToken);
    expect(notifier.activities.first['name'], 'CURRENT');

    // Applying with the current token still works normally.
    await notifier.apply([
      {'id': '1', 'name': 'FRESH'}
    ], token: notifier.token);
    expect(notifier.activities.first['name'], 'FRESH');

    // Drain both load() calls' still-pending Phase 2 fetches so nothing is
    // left hanging past the end of the test. getGeo() first — getDetails()
    // is only requested once _loadFullGeoProgressively finishes (chained via
    // whenComplete), so its completers don't exist yet at this point.
    for (final c in svc.geoCalls) {
      if (!c.isCompleted) c.complete(_emptyGeo());
    }
    await _pumpUntil(() => false, maxTicks: 5);
    for (final c in svc.detailsCalls) {
      if (!c.isCompleted) c.complete(_detailsNamed('drained'));
    }
    await _pumpUntil(() => false, maxTicks: 5);
  });
}

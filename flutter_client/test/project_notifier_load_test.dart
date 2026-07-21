// Regression test for a latent bug found while testing issue #40's view-mode
// Encounters entry point: ProjectNotifier.load() fires getLowResGeo() and
// getDetailsMeta() concurrently but awaits them sequentially. If the first one
// awaited rejects, load() returns via its catch block having never awaited
// the second future at all — if that second future later also rejects, it
// has no listener whatsoever and surfaces as an unhandled asynchronous error
// instead of being contained by load()'s try/catch.

import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

class _OrphanRiskService extends ProjectService {
  @override
  Future<Map<String, dynamic>> getLowResGeo(ProjectRef ref) async {
    await Future<void>.delayed(const Duration(milliseconds: 1));
    throw Exception('lowRes rejects first');
  }

  @override
  Future<Map<String, dynamic>> getDetailsMeta(ProjectRef ref) async {
    await Future<void>.delayed(const Duration(milliseconds: 20));
    throw Exception('details rejects later, after load() already returned');
  }

  // load() also fires these two in the background regardless of the above —
  // stub them out so this test only exercises the getLowResGeo/getDetailsMeta
  // race, not real (host-less, in-test) HTTP calls.
  @override
  Future<Map<String, dynamic>> getGeo(ProjectRef ref) async =>
      {'type': 'FeatureCollection', 'features': <dynamic>[]};

  @override
  Future<Map<String, dynamic>> getDetails(ProjectRef ref) async => {};
}

void main() {
  test(
      'load() does not leave an orphaned unhandled future when the '
      'first-awaited request fails before the second one settles', () async {
    final notifier = ProjectNotifier(_OrphanRiskService());

    await notifier.load(const ProjectRef(name: 'Trip'));
    expect(notifier.error, isNotNull);

    // Give the still-in-flight getDetailsMeta() future time to reject. Before
    // the fix this had no listener at all and would report as an unhandled
    // error in this test's zone; the fix (.ignore() on both futures at
    // creation) makes this a no-op regardless of await order.
    await Future<void>.delayed(const Duration(milliseconds: 50));
  });
}

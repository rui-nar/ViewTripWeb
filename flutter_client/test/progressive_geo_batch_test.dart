import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';

/// #4: the progressive low-res→full-res geo upgrade used to call notifyListeners
/// once per 3 activities, and each notify triggers a full map rebuild (every
/// marker + polyline). On a long trip that was ~50 rebuilds = seconds of jank.
/// The batch size now bounds repaints to ~8 regardless of trip size.
void main() {
  // Repaints during the upgrade = ceil(activityCount / batchSize).
  int repaints(int activityCount) {
    final b = progressiveGeoBatchSize(activityCount);
    return (activityCount / b).ceil();
  }

  group('progressiveGeoBatchSize', () {
    test('small trips upgrade one activity at a time (cheap anyway)', () {
      for (final n in [1, 4, 8]) {
        expect(progressiveGeoBatchSize(n), 1, reason: 'count=$n');
      }
    });

    test('repaints are bounded to ~8 no matter how large the trip', () {
      for (final n in [9, 50, 150, 500, 2000]) {
        expect(repaints(n), lessThanOrEqualTo(8), reason: 'count=$n');
      }
    });

    test('a 150-activity trip repaints ~8 times, not ~50', () {
      expect(repaints(150), lessThanOrEqualTo(8));
      // Regression guard: the old fixed batchSize=3 gave 50 repaints.
      expect((150 / 3).ceil(), 50);
    });

    test('batch size scales with trip size', () {
      expect(progressiveGeoBatchSize(150), greaterThan(progressiveGeoBatchSize(16)));
    });
  });
}

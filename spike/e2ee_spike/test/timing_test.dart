import 'dart:typed_data';

import 'package:e2ee_spike/e2ee_spike.dart';
import 'package:test/test.dart';

/// Prints Argon2id derive timing on whatever platform runs it.
/// VM:  dart test test/timing_test.dart
/// Web: dart test -p chrome test/timing_test.dart
void main() {
  final salt = Uint8List.fromList(List<int>.generate(16, (i) => i));
  final answers = ['Fluffy', 'Lisbon', 'Mrs. Object'];

  const candidates = [
    Argon2Params(memoryKib: 19456, iterations: 2, parallelism: 1),
    Argon2Params(memoryKib: 32768, iterations: 3, parallelism: 1),
    Argon2Params(memoryKib: 65536, iterations: 3, parallelism: 1),
  ];

  for (final p in candidates) {
    test('Argon2id mem=${p.memoryKib}KiB t=${p.iterations}', () async {
      await qnaWrapKey(answers, salt, p); // warm-up
      final times = <int>[];
      for (var i = 0; i < 3; i++) {
        final sw = Stopwatch()..start();
        await qnaWrapKey(answers, salt, p);
        sw.stop();
        times.add(sw.elapsedMilliseconds);
      }
      times.sort();
      // ignore: avoid_print
      print('>>> mem=${p.memoryKib}KiB t=${p.iterations}: '
          '${times.join("/")} ms (median ${times[1]} ms)');
    }, timeout: const Timeout(Duration(minutes: 2)));
  }
}

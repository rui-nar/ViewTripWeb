import 'dart:typed_data';

import 'package:e2ee_spike/e2ee_spike.dart';

/// Argon2id derive-key timing for the Option B (Q&A) wrap. Run on the VM
/// (`dart run bin/bench_argon2.dart`) and on web is not directly supported by
/// `dart run`, so web timing is captured via the timing test under
/// `dart test -p chrome` instead. This gives the native/VM baseline.
Future<void> main() async {
  final salt = Uint8List.fromList(List<int>.generate(16, (i) => i));
  final answers = ['Fluffy', 'Lisbon', 'Mrs. Object'];

  // Candidate parameter sets to compare (memory in KiB).
  const candidates = [
    Argon2Params(memoryKib: 19456, iterations: 2, parallelism: 1), // 19 MiB
    Argon2Params(memoryKib: 32768, iterations: 3, parallelism: 1), // 32 MiB
    Argon2Params(memoryKib: 65536, iterations: 3, parallelism: 1), // 64 MiB
  ];

  for (final p in candidates) {
    // warm up once (JIT / allocation), then time 3 runs.
    await qnaWrapKey(answers, salt, p);
    final times = <int>[];
    for (var i = 0; i < 3; i++) {
      final sw = Stopwatch()..start();
      await qnaWrapKey(answers, salt, p);
      sw.stop();
      times.add(sw.elapsedMilliseconds);
    }
    final median = (times..sort())[1];
    print('Argon2id mem=${p.memoryKib}KiB t=${p.iterations} p=${p.parallelism}'
        ' -> ${times.join("/")} ms (median ${median} ms)');
  }
}

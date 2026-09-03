/// Resident set size of this process, on platforms that can answer.
///
/// Exists because the remaining freeze on issue #276 shows up as a
/// multi-second frame with no instrumented work inside it, which is what a
/// major garbage collection looks like: it is attributed to whichever frame it
/// interrupts, and none of this app's spans wrap it. Dart exposes no public
/// GC-pause API outside the VM service, so process memory is the available
/// proxy — a heap holding a 33 MB details payload, expanded geometry and a
/// ~55 MB image cache is the thing that would make collections expensive.
library;

import 'dart:io' show ProcessInfo;

int? currentRssBytes() {
  try {
    return ProcessInfo.currentRss;
  } on Object {
    // Not implemented on every platform; absence is not an error.
    return null;
  }
}

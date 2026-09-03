/// Web fallback for [currentRssBytes] — `dart:io` does not exist there, and a
/// browser will not tell a page its process memory. See the native
/// implementation for why this is measured at all.
library;

int? currentRssBytes() => null;

/// Pure matching engine for the Polarsteps photo-upgrade feature (issue #33).
///
/// Takes already-extracted candidate metadata (capture time, optional GPS,
/// optional perceptual hash) — EXIF parsing and pHash computation happen in
/// later phases — and answers two pure questions: which candidates belong to
/// a given memory's day/place, and how they best pair against the memory's
/// existing thumbnail pHashes. No file I/O, no platform channels, no
/// network, so it is fully unit-testable in isolation.
library;

import 'dart:math' as math;

/// A photo picked from the user's device, with metadata already extracted
/// by a later phase (EXIF timestamp/GPS, perceptual hash).
class PhotoCandidate {
  /// Capture instant. Compared via [DateTime.toUtc], so callers don't need
  /// to normalise it before passing it in.
  final DateTime capturedAt;
  final double? lat;
  final double? lon;

  /// Pre-computed perceptual hash, or null if not yet computed.
  final int? pHash;

  const PhotoCandidate({
    required this.capturedAt,
    this.lat,
    this.lon,
    this.pHash,
  });

  bool get hasGeo => lat != null && lon != null;
}

/// Default geo tolerance for day selection: memory geo is often "start of
/// day" rather than a precise per-photo location, so this stays generous.
const double kDefaultGeoToleranceKm = 50;

/// Returns the [candidates] that belong to the memory's [date] (a
/// `YYYY-MM-DD` string) in the trip's local time, optionally narrowed to
/// within [geoToleranceKm] of ([memoryLat], [memoryLon]).
///
/// Day boundaries are computed once, in UTC (local midnight − [localOffset]
/// gives the UTC instant of local midnight), so each candidate is checked
/// with a single instant comparison rather than shifting every candidate's
/// clock and re-deriving a date — that per-candidate-shift style is the
/// classic source of an off-by-one-day bug right around midnight.
///
/// Geo filtering only applies when the memory has a location: if
/// [memoryLat]/[memoryLon] is null, every day-matched candidate is kept
/// regardless of GPS. A candidate that itself lacks GPS is also kept by the
/// day-only match — geo is a ranking signal, not a hard requirement, when
/// the photo has no coordinates of its own.
List<PhotoCandidate> selectCandidatesForDay({
  required String date,
  required Duration localOffset,
  required List<PhotoCandidate> candidates,
  double? memoryLat,
  double? memoryLon,
  double geoToleranceKm = kDefaultGeoToleranceKm,
}) {
  final dayStartUtc = _parseDateUtc(date).subtract(localOffset);
  final dayEndUtc = dayStartUtc.add(const Duration(days: 1));
  final hasMemoryGeo = memoryLat != null && memoryLon != null;

  return candidates.where((c) {
    final utc = c.capturedAt.toUtc();
    if (utc.isBefore(dayStartUtc) || !utc.isBefore(dayEndUtc)) return false;
    if (!hasMemoryGeo || !c.hasGeo) return true;
    return haversineKm(memoryLat, memoryLon, c.lat!, c.lon!) <= geoToleranceKm;
  }).toList();
}

DateTime _parseDateUtc(String date) {
  final parts = date.split('-');
  return DateTime.utc(
    int.parse(parts[0]),
    int.parse(parts[1]),
    int.parse(parts[2]),
  );
}

/// Great-circle distance in kilometres between two coordinates.
double haversineKm(double lat1, double lon1, double lat2, double lon2) {
  const r = 6371.0;
  final dLat = (lat2 - lat1) * (math.pi / 180);
  final dLon = (lon2 - lon1) * (math.pi / 180);
  final sinDLat = math.sin(dLat / 2);
  final sinDLon = math.sin(dLon / 2);
  final h = (sinDLat * sinDLat +
          math.cos(lat1 * math.pi / 180) *
              math.cos(lat2 * math.pi / 180) *
              sinDLon * sinDLon)
      .clamp(0.0, 1.0);
  return 2 * r * math.asin(math.sqrt(h));
}

/// Confidence signal for a proposed candidate/thumbnail pairing. The review
/// UI (a later phase) always requires human confirmation regardless of
/// confidence — this only controls how the pairing is flagged for review.
enum MatchConfidence {
  /// No other available candidate came close to this thumbnail's chosen
  /// distance.
  high,

  /// Another available candidate was within [PhotoMatch.hammingDistance] +
  /// the pairing's ambiguity margin of this thumbnail — don't silently
  /// resolve the tie.
  low,
}

/// A proposed 1:1 pairing between a candidate photo and an existing
/// thumbnail, by index into the lists passed to
/// [pairCandidatesWithThumbnails].
class PhotoMatch {
  final int candidateIndex;
  final int thumbnailIndex;
  final int hammingDistance;
  final MatchConfidence confidence;

  const PhotoMatch({
    required this.candidateIndex,
    required this.thumbnailIndex,
    required this.hammingDistance,
    required this.confidence,
  });
}

/// Result of [pairCandidatesWithThumbnails]: the proposed pairings plus the
/// candidate/thumbnail indices left unpaired (no pHash, no thumbnail close
/// enough, or already claimed by a closer pairing).
class MatchResult {
  final List<PhotoMatch> matches;
  final List<int> unmatchedCandidateIndices;
  final List<int> unmatchedThumbnailIndices;

  const MatchResult({
    required this.matches,
    required this.unmatchedCandidateIndices,
    required this.unmatchedThumbnailIndices,
  });
}

/// Pairs [candidates] against [thumbnailPHashes] (the memory's existing
/// thumbnail pHashes) by Hamming distance, greedily assigning the
/// closest pairs first so each side is used at most once.
///
/// [maxHammingDistance] caps how different two pHashes may be and still
/// count as the same photo (default tuned for a 64-bit pHash; adjust
/// empirically once phases 3/4 land and real hashes are available).
/// [ambiguityMargin] controls when a thumbnail's closest available
/// candidate is considered "too close to call" against the next-closest
/// one — such pairings are still made (a pick is still returned for the
/// UI to show) but flagged [MatchConfidence.low] instead of being silently
/// treated as certain. Candidates without a pHash are always left
/// unmatched.
MatchResult pairCandidatesWithThumbnails({
  required List<PhotoCandidate> candidates,
  required List<int> thumbnailPHashes,
  int maxHammingDistance = 12,
  int ambiguityMargin = 4,
}) {
  final pairs = <(int candidateIndex, int thumbnailIndex, int distance)>[];
  for (var ci = 0; ci < candidates.length; ci++) {
    final hash = candidates[ci].pHash;
    if (hash == null) continue;
    for (var ti = 0; ti < thumbnailPHashes.length; ti++) {
      final d = hammingDistance(hash, thumbnailPHashes[ti]);
      if (d <= maxHammingDistance) pairs.add((ci, ti, d));
    }
  }
  pairs.sort((a, b) => a.$3.compareTo(b.$3));

  final usedCandidates = <int>{};
  final usedThumbnails = <int>{};
  final matches = <PhotoMatch>[];

  for (final (ci, ti, d) in pairs) {
    if (usedCandidates.contains(ci) || usedThumbnails.contains(ti)) continue;

    // Any rival pairing for the same thumbnail with a *smaller* distance
    // and an unused candidate would already have been accepted earlier in
    // this loop (pairs are processed in ascending-distance order), so any
    // surviving rival here is necessarily at distance >= d — checking the
    // margin against those is enough to catch a genuine tie.
    final rival = pairs.any((p) =>
        p.$2 == ti &&
        p.$1 != ci &&
        !usedCandidates.contains(p.$1) &&
        p.$3 - d <= ambiguityMargin);

    matches.add(PhotoMatch(
      candidateIndex: ci,
      thumbnailIndex: ti,
      hammingDistance: d,
      confidence: rival ? MatchConfidence.low : MatchConfidence.high,
    ));
    usedCandidates.add(ci);
    usedThumbnails.add(ti);
  }

  final unmatchedCandidates = [
    for (var ci = 0; ci < candidates.length; ci++)
      if (!usedCandidates.contains(ci)) ci,
  ];
  final unmatchedThumbnails = [
    for (var ti = 0; ti < thumbnailPHashes.length; ti++)
      if (!usedThumbnails.contains(ti)) ti,
  ];

  return MatchResult(
    matches: matches,
    unmatchedCandidateIndices: unmatchedCandidates,
    unmatchedThumbnailIndices: unmatchedThumbnails,
  );
}

/// Hamming distance (bit difference count) between two perceptual hashes.
int hammingDistance(int a, int b) {
  var x = a ^ b;
  var count = 0;
  for (var i = 0; i < 64; i++) {
    if ((x & 1) != 0) count++;
    x = x >>> 1;
  }
  return count;
}

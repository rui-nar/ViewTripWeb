/// Pure rules for the days that fall after a trip's end date.
///
/// Split out of project_settings_screen.dart so the claim the "Remove days
/// after the end date?" confirmation makes can be unit-tested on its own
/// (issue #358), and so the day list here and the one the trip actually
/// renders are derived from the same extraction.
library;

/// The days sitting after a trip end date, split by whether dropping their
/// day-meta entry actually makes them disappear from the trip.
class TripEndOrphans {
  /// Days after the end date whose only content is day-meta. Removing that
  /// entry removes the day.
  final List<String> removable;

  /// Days after the end date that carry trip content — an activity, a memory,
  /// a journal entry, an encounter or a dated segment, belonging to *any*
  /// member of the trip. The trip's day list is the union of day-meta keys
  /// and these content days (see [ProjectNotifier.orderedDayKeys]), so these
  /// stay visible whatever day-meta says. Their day-meta is deliberately left
  /// alone: silently wiping the notes of a day the user can still see would
  /// be worse than leaving them.
  ///
  /// Journal entries are per-user server-side, so [contentDayKeys] on its own
  /// cannot see a day another member's journal keeps on screen (issue #372).
  /// The caller fills [daysWithContent] from
  /// GET /api/projects/{name}/content-days, which answers for every member,
  /// and unions the local extraction in for edits the server hasn't seen yet.
  final List<String> pinned;

  const TripEndOrphans({required this.removable, required this.pinned});
}

/// Day keys ("YYYY-MM-DD") that carry trip content — an activity, or an item
/// of any type (memory, journal, encounter, segment).
///
/// Every one of those buckets into a day header in the activity panel (see
/// `_buildDisplayList`), so every one of them keeps a day on screen no matter
/// what day-meta says. Items with no date of their own inherit the preceding
/// dated item's date there, which can never introduce a day key the dated
/// item did not already contribute — so ignoring that propagation here is
/// safe for the *set* of days.
///
/// Caller-local by construction: [items] never holds another member's journal
/// entries. See [TripEndOrphans.pinned] for why that is only half the answer
/// on a shared trip.
Set<String> contentDayKeys(
  List<Map<String, dynamic>> activities,
  List<Map<String, dynamic>> items,
) {
  final keys = <String>{};
  void add(String? raw) {
    final ds = raw?.split('T').first;
    if (ds != null && ds.isNotEmpty) keys.add(ds);
  }

  for (final a in activities) {
    add(a['start_date_local'] as String?);
  }
  for (final item in items) {
    final type = item['item_type'];
    if (type == 'activity') continue; // dated via `activities` above
    final body = item[type] as Map<String, dynamic>?;
    add(body?['date'] as String?);
  }
  return keys;
}

/// Classifies every day in [dayKeys] strictly after [tripEnd] (both plain
/// "YYYY-MM-DD", so a lexicographic compare is a date compare). Both returned
/// lists are sorted ascending and duplicate-free.
TripEndOrphans classifyTripEndOrphans({
  required Iterable<String> dayKeys,
  required Set<String> daysWithContent,
  required String tripEnd,
}) {
  final removable = <String>[];
  final pinned = <String>[];
  for (final key in dayKeys.toSet().toList()..sort()) {
    if (key.compareTo(tripEnd) <= 0) continue;
    (daysWithContent.contains(key) ? pinned : removable).add(key);
  }
  return TripEndOrphans(removable: removable, pinned: pinned);
}

/// Why the cross-member content check could not be answered.
enum ContentCheckFailure {
  /// The server was not reached at all — a genuine "you look offline".
  unreachable,

  /// The server answered and refused (404 on an older server, 403, 5xx). The
  /// user is online, so telling them to reconnect would be wrong.
  refused,
}

/// Builds the body of the "days after the end date" confirmation.
///
/// Pure so the copy can be unit-tested: the wrong sentence here is not
/// cosmetic. Telling someone to "move or delete that content first" for a day
/// pinned by *another member's* journal asks for something they can neither
/// see nor touch, and saying "you're offline" when the server answered and
/// refused sends them to fix the wrong thing.
///
/// [gone] is how many days will actually be deleted; [visibleKept] how many
/// stay because of content this user can see and act on; [hiddenKept] how many
/// stay because of content only the server can see. [failure] non-null means
/// the check could not be run, in which case nothing is deleted.
String tripEndWarningMessage({
  required int gone,
  required int visibleKept,
  required int hiddenKept,
  required String when,
  ContentCheckFailure? failure,
}) {
  String days(int n) => '$n day${n == 1 ? '' : 's'}';
  final out = <String>[];

  if (gone > 0) {
    out.add('${days(gone)} after $when will be deleted.');
  }
  if (failure != null) {
    // An unanswered check pins every candidate, so gone is 0 here.
    out.add('${days(visibleKept + hiddenKept)} after $when may hold content '
        'from other trip members. That could not be checked just now, so '
        'nothing will be deleted — '
        '${failure == ContentCheckFailure.unreachable
            ? 'try again once you are back online.'
            : 'the server could not answer that check.'}');
    return out.join('\n\n');
  }
  if (visibleKept > 0) {
    out.add('${days(visibleKept)} after $when still '
        '${visibleKept == 1 ? 'has' : 'have'} trip content on '
        '${visibleKept == 1 ? 'it' : 'them'} and will stay in the trip — move '
        'or delete that content first.');
  }
  if (hiddenKept > 0) {
    out.add('${days(hiddenKept)} after $when '
        '${hiddenKept == 1 ? 'holds' : 'hold'} content belonging to other trip '
        '${hiddenKept == 1 ? 'member' : 'members'} and will stay in the trip. '
        'Only they can remove it.');
  }
  return out.join('\n\n');
}

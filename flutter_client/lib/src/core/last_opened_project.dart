/// Shared helpers for remembering the last project a user opened (issue #93),
/// so the bare-root route (`/`) can bypass `/projects` and drop the user
/// straight back into it. Scoped per-user (by [userId]) so a shared
/// browser/device doesn't leak user A's last trip into user B's session.
library;

import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'project_ref.dart';

String _prefKey(String userId) => 'last_opened_project_$userId';

/// Records [ref] as [userId]'s last successfully opened project (name +
/// owner — issue #106, so a shared project's owner survives a reload).
/// No-op if [userId] is null (not logged in / auth not resolved yet).
Future<void> saveLastOpenedProject(String? userId, ProjectRef ref) async {
  if (userId == null) return;
  final prefs = await SharedPreferences.getInstance();
  await prefs.setString(_prefKey(userId), jsonEncode(ref.toJson()));
}

/// Reads [userId]'s last-opened project ref, or null if none is recorded.
/// No-op (returns null) if [userId] is null. Backward compatible with the
/// pre-#106 format, which stored the bare project name as a plain string.
Future<ProjectRef?> readLastOpenedProject(String? userId) async {
  if (userId == null) return null;
  final prefs = await SharedPreferences.getInstance();
  final raw = prefs.getString(_prefKey(userId));
  if (raw == null || raw.isEmpty) return null;
  try {
    final decoded = jsonDecode(raw);
    if (decoded is Map) {
      return ProjectRef.fromJson(decoded.cast<String, dynamic>());
    }
  } catch (_) {
    // Not JSON — pre-#106 plain project-name string.
  }
  return ProjectRef(name: raw);
}

/// Resolves where the bare-root route (`/`) should send a logged-in user:
/// their last-opened project (`/view?project=<name>[&owner=<id>]`) if one is
/// recorded for [userId], otherwise `/projects`.
Future<String> rootRedirectTarget(String? userId) async {
  final lastRef = await readLastOpenedProject(userId);
  if (lastRef != null && lastRef.name.isNotEmpty) {
    return lastRef.withOwner('/view?project=${Uri.encodeComponent(lastRef.name)}');
  }
  return '/projects';
}

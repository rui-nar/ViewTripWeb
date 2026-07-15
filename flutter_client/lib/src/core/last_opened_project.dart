/// Shared helpers for remembering the last project a user opened (issue #93),
/// so the bare-root route (`/`) can bypass `/projects` and drop the user
/// straight back into it. Scoped per-user (by [userId]) so a shared
/// browser/device doesn't leak user A's last trip into user B's session.
library;

import 'package:shared_preferences/shared_preferences.dart';

String _prefKey(String userId) => 'last_opened_project_$userId';

/// Records [projectName] as [userId]'s last successfully opened project.
/// No-op if [userId] is null (not logged in / auth not resolved yet).
Future<void> saveLastOpenedProject(String? userId, String projectName) async {
  if (userId == null) return;
  final prefs = await SharedPreferences.getInstance();
  await prefs.setString(_prefKey(userId), projectName);
}

/// Reads [userId]'s last-opened project name, or null if none is recorded.
/// No-op (returns null) if [userId] is null.
Future<String?> readLastOpenedProject(String? userId) async {
  if (userId == null) return null;
  final prefs = await SharedPreferences.getInstance();
  return prefs.getString(_prefKey(userId));
}

/// Resolves where the bare-root route (`/`) should send a logged-in user:
/// their last-opened project (`/view?project=<name>`) if one is recorded
/// for [userId], otherwise `/projects`.
Future<String> rootRedirectTarget(String? userId) async {
  final lastProject = await readLastOpenedProject(userId);
  if (lastProject != null && lastProject.isNotEmpty) {
    return '/view?project=${Uri.encodeComponent(lastProject)}';
  }
  return '/projects';
}

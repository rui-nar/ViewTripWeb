/// Recovery from a stale shared-project ref (issue #111).
///
/// A companion addresses a shared trip by `{name, ownerId}` (see
/// [ProjectRef]), but the owner can rename the trip at any time — the stored
/// last-opened ref or an open URL then 404s. Memberships are keyed by project
/// id server-side, so the renamed trip still appears in `/api/projects/`
/// under its new name with the same `owner_id`; that is what recovery
/// re-matches against.
library;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../auth/auth_notifier.dart';
import '../projects/projects_service.dart';
import 'last_opened_project.dart';
import 'project_ref.dart';

/// Re-identifies [stale] among refreshed projects-list [entries]: the single
/// editor-role entry with the same owner. Returns null when the membership is
/// gone (revoked / trip deleted) or when several shared trips from that owner
/// make the match ambiguous. Pure — see stale_shared_ref_test.dart.
ProjectRef? recoverStaleSharedRef(
    ProjectRef stale, List<Map<String, dynamic>> entries) {
  if (stale.isOwn) return null;
  final candidates = [
    for (final e in entries)
      if (e.isSharedWithMe && e.ref.ownerId == stale.ownerId) e.ref,
  ];
  return candidates.length == 1 ? candidates.first : null;
}

/// Handles a 404 on [staleRef] (a shared project) for a screen at
/// [routePath] (`/view` or `/app`): refreshes the projects list and, when
/// the trip is unambiguously re-identified under a new name, records it as
/// last-opened and reopens it in place. Otherwise clears the last-opened
/// pref — so the bare-root redirect can't loop back into the dead ref — and
/// lands on /projects with a notice.
Future<void> recoverFromStaleSharedRef(
  BuildContext context, {
  required ProjectRef staleRef,
  required String routePath,
  ProjectsService? service,
}) async {
  final userId = context.read<AuthNotifier>().user?.id;
  List<Map<String, dynamic>> entries = const [];
  try {
    entries = await (service ?? ProjectsService()).list();
  } on Exception {
    // List refresh failed too — fall through to the /projects notice.
  }
  if (!context.mounted) return;

  final renamed = recoverStaleSharedRef(staleRef, entries);
  if (renamed != null) {
    await saveLastOpenedProject(userId, renamed);
    if (!context.mounted) return;
    context.go(
        Uri(path: routePath, queryParameters: renamed.routeParams).toString());
    return;
  }

  await clearLastOpenedProject(userId);
  if (!context.mounted) return;
  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
      content: Text('That shared trip is no longer available under its '
          'previous name — it may have been renamed or unshared.')));
  context.go('/projects');
}

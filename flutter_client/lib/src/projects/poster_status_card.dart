/// Small, passive, non-blocking poster-job status indicator (issue #14, unit
/// G) — a card overlaid on the map showing "Generating…" / done / failed for
/// the poster job the current client instance started or resumed.
///
/// This is deliberately NOT the old blocking modal that used to poll a job to
/// completion (removed because it reported false "timed out" failures on
/// real A0 renders that legitimately run past its wait budget — see
/// `poster_job_notifier.dart`'s library doc). Here, polling only ever drives
/// this small ambient card, never blocks the UI, and a long-running job is
/// never treated as failed by timeout — only a genuine `status == "failed"`
/// response from [fetchPosterJobStatus] counts as failed. After
/// [PosterStatusNotifier.giveUpAfter] of polling with no terminal status,
/// polling stops silently and the card is left in its last known state
/// (still "Generating…") — email is the authoritative word for very long
/// jobs, this card is just a convenience.
///
/// [PosterStatusNotifier] is a plain [ChangeNotifier] (no widget/context
/// dependency) so its poll/give-up state machine is unit-testable without
/// pumping a widget tree — see `poster_status_card_test.dart`. It also
/// persists the tracked job to `shared_preferences` (mirroring the
/// read/write/remove convention in `core/last_opened_project.dart`) so
/// navigating away from the map screen and back within the same app session
/// resumes tracking, per [resume]'s one-shot check-then-resume-or-clear rule.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/client.dart';
import '../core/design_tokens.dart' show kShadow2;
import '../core/project_ref.dart';
import 'poster_job_notifier.dart';

/// What the status card should currently render. `hidden` means nothing to
/// show — no card in the tree.
enum PosterCardState { hidden, generating, done, failed }

const _kPosterJobPrefKey = 'poster_job_pending';

/// Persists the job being tracked (issue #14 unit G, rule 5 — resumable
/// across navigation within the same session). Single entry: only one job is
/// ever tracked at a time (rule 3), so unlike `last_opened_project.dart` this
/// isn't scoped per-user — there is nothing to disambiguate within one
/// client instance's own session.
Future<void> _savePendingJob(ProjectRef ref, int jobId) async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.setString(
      _kPosterJobPrefKey, jsonEncode({...ref.toJson(), 'jobId': jobId}));
}

/// Forgets the tracked job — called once it's confirmed terminal and shown,
/// or once the user dismisses a terminal-state card (rule 5).
Future<void> _clearPendingJob() async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.remove(_kPosterJobPrefKey);
}

/// Reads the persisted job, or null if none is recorded / it doesn't parse.
Future<(ProjectRef, int)?> _readPendingJob() async {
  final prefs = await SharedPreferences.getInstance();
  final raw = prefs.getString(_kPosterJobPrefKey);
  if (raw == null || raw.isEmpty) return null;
  try {
    final decoded = jsonDecode(raw);
    if (decoded is Map) {
      final map = decoded.cast<String, dynamic>();
      final jobId = map['jobId'] as int?;
      if (jobId == null) return null;
      return (ProjectRef.fromJson(map), jobId);
    }
  } catch (_) {
    // Not valid JSON for this shape — treat as no persisted job.
  }
  return null;
}

/// Poll/give-up state machine for the poster status card. Deliberately a
/// fresh, minimal class — not the old deleted `PosterJobNotifier` — that owns
/// only card display state, never blocks, and never turns a long render into
/// a false failure.
class PosterStatusNotifier extends ChangeNotifier {
  /// Injectable for tests; production uses the shared [api] singleton.
  final ApiClient? client;

  /// How often to poll while a job is being tracked. 5s per issue #14's
  /// design (REST-only, no websockets, so polling is the only option).
  final Duration pollInterval;

  /// How long to keep polling a non-terminal job before giving up silently
  /// and leaving the card in its last known ("Generating…") state. 20
  /// minutes per issue #14 — long enough that a real A0 render finishing
  /// after this is expected, not exceptional; email is authoritative for it.
  final Duration giveUpAfter;

  /// Injectable clock so [giveUpAfter] is testable without waiting 20 real
  /// minutes — tests advance a fake `now` instead of the poll timer itself.
  final DateTime Function() _now;

  PosterStatusNotifier({
    this.client,
    this.pollInterval = const Duration(seconds: 5),
    this.giveUpAfter = const Duration(minutes: 20),
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;

  PosterCardState state = PosterCardState.hidden;
  String? stage;

  ProjectRef? _ref;
  int? _jobId;
  Timer? _timer;
  DateTime? _startedAt;

  /// Begins tracking [jobId] for [ref]: switches the card to "generating",
  /// persists the job so [resume] can pick it back up after navigation, and
  /// starts polling. Replaces whatever job was previously tracked (rule 3 —
  /// one job at a time, no stack of cards).
  Future<void> start({required ProjectRef ref, required int jobId}) async {
    _timer?.cancel();
    _ref = ref;
    _jobId = jobId;
    _startedAt = _now();
    stage = null;
    state = PosterCardState.generating;
    notifyListeners();
    await _savePendingJob(ref, jobId);
    _schedulePoll();
  }

  /// One-shot resume check for [ref] (rule 5): if a job is persisted for
  /// this project, checks its status exactly once. A terminal or unreadable
  /// (stale) result just clears the persisted entry and shows nothing — the
  /// user already saw the SnackBar when they started it, and a terminal
  /// result reached without this card visible isn't worth surfacing after
  /// the fact. A still-pending/running job resumes polling and the card
  /// reappears. No-op if the persisted job belongs to a different project,
  /// or none is persisted, or a job is already being tracked.
  Future<void> resume(ProjectRef ref) async {
    if (_jobId != null) return;
    final pending = await _readPendingJob();
    if (pending == null) return;
    final (pendingRef, jobId) = pending;
    if (pendingRef.name != ref.name || pendingRef.ownerId != ref.ownerId) return;

    try {
      final status = await fetchPosterJobStatus(ref: ref, jobId: jobId, client: client);
      if (status.isTerminal) {
        await _clearPendingJob();
        return;
      }
      _ref = ref;
      _jobId = jobId;
      _startedAt = _now();
      stage = status.stage;
      state = PosterCardState.generating;
      notifyListeners();
      _schedulePoll();
    } catch (_) {
      // Stale/unreadable (e.g. the job no longer exists) — nothing to resume.
      await _clearPendingJob();
    }
  }

  void _schedulePoll() {
    _timer = Timer(pollInterval, _poll);
  }

  Future<void> _poll() async {
    final ref = _ref;
    final jobId = _jobId;
    final startedAt = _startedAt;
    if (ref == null || jobId == null || startedAt == null) return;

    // Never treat a long-running job as failed by timeout — just stop
    // polling silently and leave the card in its last known state.
    if (_now().difference(startedAt) >= giveUpAfter) return;

    try {
      final status = await fetchPosterJobStatus(ref: ref, jobId: jobId, client: client);
      stage = status.stage;
      if (status.isDone) {
        state = PosterCardState.done;
        notifyListeners();
        await _clearPendingJob();
        return;
      }
      if (status.isFailed) {
        state = PosterCardState.failed;
        notifyListeners();
        await _clearPendingJob();
        return;
      }
      notifyListeners();
      _schedulePoll();
    } catch (_) {
      // Transient network hiccup — keep polling rather than surfacing an
      // error the server itself hasn't reported.
      _schedulePoll();
    }
  }

  /// Clears the persisted entry and hides the card. The only way a
  /// terminal-state card goes away — no auto-hide timer (rule 2).
  Future<void> dismiss() async {
    _timer?.cancel();
    _timer = null;
    _ref = null;
    _jobId = null;
    stage = null;
    state = PosterCardState.hidden;
    notifyListeners();
    await _clearPendingJob();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}

/// The card itself: small, rounded, matching this codebase's floating-overlay
/// convention (see `_FramePickerOverlay`'s control bar and
/// `SelectionStatsOverlay` in `map_panel.dart` for the visual it mirrors —
/// `cs.surface` at high alpha, `BorderRadius.circular(12)`, [kShadow2]).
/// Renders nothing when [PosterStatusNotifier.state] is `hidden`.
class PosterStatusCard extends StatelessWidget {
  final PosterStatusNotifier notifier;

  const PosterStatusCard({super.key, required this.notifier});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: notifier,
      builder: (context, _) {
        if (notifier.state == PosterCardState.hidden) return const SizedBox.shrink();
        final cs = Theme.of(context).colorScheme;
        return Container(
          padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
          decoration: BoxDecoration(
            color: cs.surface.withValues(alpha: 0.95),
            borderRadius: BorderRadius.circular(12),
            boxShadow: kShadow2(Theme.of(context).brightness),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              ..._leading(cs),
              const SizedBox(width: 8),
              Text(_label, style: TextStyle(fontSize: 12.5, color: cs.onSurface)),
              if (notifier.state != PosterCardState.generating) ...[
                const SizedBox(width: 2),
                IconButton(
                  tooltip: 'Dismiss',
                  icon: const Icon(Icons.close, size: 16),
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
                  onPressed: notifier.dismiss,
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  List<Widget> _leading(ColorScheme cs) {
    switch (notifier.state) {
      case PosterCardState.generating:
        return const [
          SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2)),
        ];
      case PosterCardState.done:
        return [Icon(Icons.check_circle, size: 18, color: cs.primary)];
      case PosterCardState.failed:
        return [Icon(Icons.error_outline, size: 18, color: cs.error)];
      case PosterCardState.hidden:
        return const [];
    }
  }

  String get _label {
    switch (notifier.state) {
      case PosterCardState.generating:
        return 'Generating poster…';
      case PosterCardState.done:
        // Not "download it here" — the download link/token is only ever
        // handed out by email (see poster_download_screen.dart); this card
        // has no download affordance of its own.
        return 'Poster ready — check your email';
      case PosterCardState.failed:
        // Generic on purpose — errorMessage can carry internal detail, same
        // restraint the failure email applies (see PosterJobStatus.errorMessage).
        return 'Poster generation failed';
      case PosterCardState.hidden:
        return '';
    }
  }
}

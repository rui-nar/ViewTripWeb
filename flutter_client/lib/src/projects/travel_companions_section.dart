/// "Travel companions" settings section (issue #106).
///
/// Rendered inside ProjectSettingsScreen's section card. Owner view: member
/// list with per-member remove, plus an invite-link block (create → copy URL →
/// revoke; a 409 from an E2EE-enabled account surfaces the server's message
/// inline). Editor view: read-only member list plus a "Leave trip" action
/// that removes the caller's own membership and returns to the projects list.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../api/client.dart';
import '../auth/auth_notifier.dart';
import '../core/design_tokens.dart' show kWarningDark;
import '../core/last_opened_project.dart';
import 'members_service.dart';
import 'project_notifier.dart';
import 'projects_notifier.dart';

// Local palette mirroring project_settings_screen.dart's design tokens so the
// section blends into the settings screen it is embedded in.
const _kBg = Color(0xFF0A1320);
const _kBgCard = Color(0xFF0F1A26);
const _kBorder = Color(0xFF1F2F42);
const _kText1 = Color(0xFFF1F5F9);
const _kText2 = Color(0xFFCBD5E1);
const _kMuted = Color(0xFF94A3B8);
const _kDim = Color(0xFF64748B);
const _kBlueActive = Color(0xFF60A5FA);
const _kRed = Color(0xFFEF4444);

/// Extracts the server's `detail` message out of an exception, mirroring
/// ProjectNotifier._msg.
String companionErrorMessage(Object e) {
  final s = e.toString();
  final m = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(s);
  return m?.group(1) ?? s.replaceFirst('Exception: ', '');
}

class TravelCompanionsSection extends StatefulWidget {
  const TravelCompanionsSection({super.key});

  @override
  State<TravelCompanionsSection> createState() =>
      _TravelCompanionsSectionState();
}

class _TravelCompanionsSectionState extends State<TravelCompanionsSection> {
  bool _loading = true;
  String? _loadError;

  // Inline error under the invite block (409 E2EE message, network errors).
  String? _inviteError;
  bool _inviteBusy = false;
  bool _leaving = false;

  @override
  void initState() {
    super.initState();
    // Deferred: loadMembers() calls notifyListeners(), which must not fire
    // during the first build (see feedback_patterns — ValueNotifier timing).
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    if (!mounted) return;
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      await context.read<ProjectNotifier>().loadMembers();
      if (mounted) setState(() => _loading = false);
    } on Exception catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _loadError = companionErrorMessage(e);
        });
      }
    }
  }

  String _joinUrl(String token) {
    var origin = api.baseUrl;
    if (origin.isEmpty) {
      try {
        origin = Uri.base.origin;
      } catch (_) {
        // Non-http Uri.base (tests) — relative URL is still copyable.
      }
    }
    return '$origin/join/$token';
  }

  Future<void> _createInvite() async {
    setState(() {
      _inviteBusy = true;
      _inviteError = null;
    });
    try {
      await context.read<ProjectNotifier>().createMemberInvite();
    } on Exception catch (e) {
      // 409 (E2EE-enabled account) and any other failure surface inline —
      // no dialog.
      if (mounted) setState(() => _inviteError = companionErrorMessage(e));
    } finally {
      if (mounted) setState(() => _inviteBusy = false);
    }
  }

  Future<void> _revokeInvite() async {
    setState(() {
      _inviteBusy = true;
      _inviteError = null;
    });
    try {
      await context.read<ProjectNotifier>().revokeMemberInvite();
    } on Exception catch (e) {
      if (mounted) setState(() => _inviteError = companionErrorMessage(e));
    } finally {
      if (mounted) setState(() => _inviteBusy = false);
    }
  }

  Future<void> _removeMember(ProjectMember member) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove companion?'),
        content: Text(
          '${member.displayName.isEmpty ? 'This member' : member.displayName} '
          'will lose access to this trip. Their journal entries stay private '
          'to them.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(minimumSize: const Size(96, 44)),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await context.read<ProjectNotifier>().removeMember(member.userId);
    } on Exception catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(companionErrorMessage(e))));
      }
    }
  }

  Future<void> _leaveTrip(ProjectMember self) async {
    final notifier = context.read<ProjectNotifier>();
    final projectName = notifier.projectName ?? '';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Leave trip?'),
        content: Text(
          'You will lose access to "$projectName" until the owner invites '
          'you again.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(minimumSize: const Size(96, 44)),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Leave'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _leaving = true);
    try {
      final leftRef = notifier.ref;
      final userId = context.read<AuthNotifier>().user?.id;
      await notifier.removeMember(self.userId);
      // Forget the last-opened project if it was this one, so the bare-root
      // redirect doesn't drop the user back into a trip they just left.
      if (leftRef != null) {
        final last = await readLastOpenedProject(userId);
        if (last != null &&
            last.name == leftRef.name &&
            last.ownerId == leftRef.ownerId) {
          await clearLastOpenedProject(userId);
        }
      }
      if (!mounted) return;
      // Refresh the projects list (drops the trip from "Shared With Me").
      try {
        context.read<ProjectsNotifier>().load();
      } on ProviderNotFoundException {
        // Not in the tree (tests) — the list reloads on next visit anyway.
      }
      context.go('/projects');
    } on Exception catch (e) {
      if (mounted) {
        setState(() => _leaving = false);
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(companionErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final notifier = context.watch<ProjectNotifier>();
    final selfId = context.watch<AuthNotifier>().user?.id;
    final isEditor = notifier.isEditor;
    final members = notifier.members;
    final ownRow = [
      for (final m in members)
        if (m.userId.toString() == selfId) m
    ];

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 20),
              child: Center(
                child: SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2)),
              ),
            )
          else if (_loadError != null)
            Text(_loadError!,
                style: const TextStyle(color: _kRed, fontSize: 12.5))
          else ...[
            for (final m in members)
              _MemberRow(
                member: m,
                isSelf: m.userId.toString() == selfId,
                // Owner can remove any non-owner member; editors see a
                // read-only list.
                onRemove: !isEditor && !m.isOwner ? () => _removeMember(m) : null,
              ),
            if (!isEditor) ...[
              const SizedBox(height: 8),
              _inviteBlock(notifier),
            ],
            if (isEditor && ownRow.isNotEmpty) ...[
              const SizedBox(height: 12),
              const Divider(height: 1, color: _kBorder),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                  foregroundColor: _kRed,
                  side: const BorderSide(color: Color(0x47EF4444)),
                ),
                icon: _leaving
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.logout, size: 15),
                label: const Text('Leave trip'),
                onPressed: _leaving ? null : () => _leaveTrip(ownRow.first),
              ),
            ],
          ],
        ],
      ),
    );
  }

  Widget _inviteBlock(ProjectNotifier notifier) {
    final token = notifier.memberInviteToken;
    return Container(
      decoration: BoxDecoration(
        color: _kBg,
        border: Border.all(color: _kBorder),
        borderRadius: BorderRadius.circular(12),
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Invite link',
                        style: TextStyle(
                            fontWeight: FontWeight.w700,
                            fontSize: 14,
                            color: _kText1)),
                    Text(
                      'Anyone with the link who signs in can join as editor.',
                      style: TextStyle(fontSize: 12, color: _kDim),
                    ),
                  ],
                ),
              ),
              if (token != null)
                TextButton(
                  style: TextButton.styleFrom(
                    foregroundColor: _kRed,
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    visualDensity: VisualDensity.compact,
                  ),
                  onPressed: _inviteBusy ? null : _revokeInvite,
                  child: const Text('Revoke',
                      style: TextStyle(fontWeight: FontWeight.w600)),
                ),
            ],
          ),
          const SizedBox(height: 10),
          if (token == null)
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                foregroundColor: _kBlueActive,
                side: const BorderSide(color: Color(0x473B82F6)),
                backgroundColor: const Color(0x1A3B82F6),
              ),
              icon: _inviteBusy
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.person_add_alt, size: 15),
              label: const Text('Create invite link'),
              onPressed: _inviteBusy ? null : _createInvite,
            )
          else
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: const Color(0x220A1320),
                border: Border.all(color: _kBorder),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      _joinUrl(token),
                      style: const TextStyle(
                        fontFamily: 'monospace',
                        fontSize: 12,
                        color: _kMuted,
                        overflow: TextOverflow.ellipsis,
                      ),
                      maxLines: 1,
                    ),
                  ),
                  const SizedBox(width: 8),
                  InkWell(
                    onTap: () => Clipboard.setData(
                        ClipboardData(text: _joinUrl(token))),
                    child: Container(
                      width: 28,
                      height: 28,
                      decoration: BoxDecoration(
                        color: const Color(0x1A3B82F6),
                        border: Border.all(color: const Color(0x473B82F6)),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: const Icon(Icons.content_copy,
                          size: 14, color: _kBlueActive),
                    ),
                  ),
                ],
              ),
            ),
          if (_inviteError != null) ...[
            const SizedBox(height: 8),
            Text(
              _inviteError!,
              style: const TextStyle(color: kWarningDark, fontSize: 12.5),
            ),
          ],
        ],
      ),
    );
  }
}

class _MemberRow extends StatelessWidget {
  final ProjectMember member;
  final bool isSelf;
  final VoidCallback? onRemove;

  const _MemberRow({required this.member, required this.isSelf, this.onRemove});

  @override
  Widget build(BuildContext context) {
    final name = member.displayName.isEmpty ? '(unknown)' : member.displayName;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: _kBg,
          border: Border.all(color: _kBorder),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(
          children: [
            CircleAvatar(
              radius: 14,
              backgroundColor: const Color(0xFF1D4ED8),
              foregroundImage: member.avatarUrl.isNotEmpty
                  ? NetworkImage(member.avatarUrl)
                  : null,
              child: Text(
                name[0].toUpperCase(),
                style: const TextStyle(fontSize: 12, color: Colors.white),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                isSelf ? '$name (you)' : name,
                style: const TextStyle(color: _kText2, fontSize: 13.5),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: member.isOwner ? const Color(0x1A3B82F6) : _kBgCard,
                border: Border.all(
                    color: member.isOwner
                        ? const Color(0x473B82F6)
                        : _kBorder),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text(
                member.role,
                style: TextStyle(
                  color: member.isOwner ? _kBlueActive : _kMuted,
                  fontSize: 11,
                  fontFamily: 'monospace',
                ),
              ),
            ),
            if (onRemove != null) ...[
              const SizedBox(width: 4),
              IconButton(
                icon: const Icon(Icons.person_remove_outlined,
                    size: 16, color: _kDim),
                visualDensity: VisualDensity.compact,
                tooltip: 'Remove from trip',
                onPressed: onRemove,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

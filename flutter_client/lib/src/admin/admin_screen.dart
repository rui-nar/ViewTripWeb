/// Admin dashboard — aggregate metrics, per-user breakdown, and a tier-gated
/// user search + password-reset tool. Shown only to admins (see app_router).
///
/// Never renders memory/journal content: the backend only exposes counts,
/// sizes, and profile fields.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../core/design_tokens.dart';
import 'admin_service.dart';

/// Human-readable byte size (e.g. 1.5 MB). Kept top-level so tests can exercise it.
String humanizeBytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  const units = ['KB', 'MB', 'GB', 'TB'];
  double value = bytes / 1024;
  int i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return '${value.toStringAsFixed(value >= 10 ? 0 : 1)} ${units[i]}';
}

/// Signup date from a Unix-seconds timestamp → "YYYY-MM-DD" (empty when 0).
String formatSignup(num createdAt) {
  if (createdAt <= 0) return '—';
  final dt = DateTime.fromMillisecondsSinceEpoch(
      (createdAt * 1000).round(),
      isUtc: true);
  final m = dt.month.toString().padLeft(2, '0');
  final d = dt.day.toString().padLeft(2, '0');
  return '${dt.year}-$m-$d';
}

/// Color for an encryption-tier chip.
Color tierColor(String tier) {
  switch (tier) {
    case 'high':
      return kSuccess;
    case 'medium':
      return kWarning;
    case 'low':
      return kColorRide;
    default:
      return kColorOther;
  }
}

class AdminScreen extends StatefulWidget {
  /// Injectable for tests; defaults to the real HTTP-backed service.
  final AdminService service;

  AdminScreen({super.key, AdminService? service})
      : service = service ?? AdminService();

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  Map<String, dynamic>? _stats;
  bool _loading = true;
  String? _error;
  bool _refreshingStorage = false;

  // ── Search state ────────────────────────────────────────────────────────────
  final _searchCtrl = TextEditingController();
  List<Map<String, dynamic>> _results = [];
  bool _searching = false;
  final Set<int> _resetting = {};
  final Set<int> _togglingAdmin = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final stats = await widget.service.getStats();
      if (mounted) setState(() => _stats = stats);
    } catch (e) {
      if (mounted) {
        setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _recalculateStorage() async {
    setState(() => _refreshingStorage = true);
    try {
      await widget.service.refreshStorage();
      await _load();
    } catch (_) {
    } finally {
      if (mounted) setState(() => _refreshingStorage = false);
    }
  }

  Future<void> _search() async {
    final q = _searchCtrl.text.trim();
    if (q.isEmpty) {
      setState(() => _results = []);
      return;
    }
    setState(() => _searching = true);
    try {
      final res = await widget.service.searchUsers(q);
      if (mounted) setState(() => _results = res);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Search failed: '
              '${e.toString().replaceFirst('Exception: ', '')}')),
        );
      }
    } finally {
      if (mounted) setState(() => _searching = false);
    }
  }

  Future<void> _resetPassword(Map<String, dynamic> user) async {
    final id = user['id'] as int;
    setState(() => _resetting.add(id));
    try {
      final temp = await widget.service.resetPassword(id);
      if (mounted) _showTempPasswordDialog(user, temp);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.toString().replaceFirst('Exception: ', ''))),
        );
      }
    } finally {
      if (mounted) setState(() => _resetting.remove(id));
    }
  }

  Future<void> _toggleAdmin(Map<String, dynamic> user) async {
    final id = user['id'] as int;
    final grant = !(user['is_admin'] == true);
    setState(() => _togglingAdmin.add(id));
    try {
      await widget.service.setAdmin(id, grant);
      if (mounted) setState(() => user['is_admin'] = grant);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.toString().replaceFirst('Exception: ', ''))),
        );
      }
    } finally {
      if (mounted) setState(() => _togglingAdmin.remove(id));
    }
  }

  void _showTempPasswordDialog(Map<String, dynamic> user, String temp) {
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Temporary password'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('For ${user['display_name'] ?? user['email'] ?? 'user'}:'),
            const SizedBox(height: 12),
            SelectableText(temp, style: monoStyle(fontSize: 16)),
            const SizedBox(height: 12),
            Text(
              'Shown once. The user must change it on next login.',
              style: Theme.of(ctx).textTheme.bodySmall,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              Clipboard.setData(ClipboardData(text: temp));
              ScaffoldMessenger.of(ctx).showSnackBar(
                const SnackBar(content: Text('Copied')),
              );
            },
            child: const Text('Copy'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Done'),
          ),
        ],
      ),
    );
  }

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: BackButton(onPressed: () => context.pop()),
        title: const Text('Admin'),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? _ErrorView(message: _error!, onRetry: _load)
              : _buildContent(context),
    );
  }

  Widget _buildContent(BuildContext context) {
    final totals = (_stats?['totals'] as Map?)?.cast<String, dynamic>() ?? {};
    final users = ((_stats?['users'] as List?) ?? [])
        .cast<Map<String, dynamic>>();

    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 960),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _SectionCard(
                title: 'Overview',
                icon: Icons.dashboard_outlined,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 12,
                      runSpacing: 12,
                      children: [
                        _MetricTile(label: 'Users', value: '${totals['users'] ?? 0}'),
                        _MetricTile(label: 'Projects', value: '${totals['projects'] ?? 0}'),
                        _MetricTile(label: 'Activities', value: '${totals['activities'] ?? 0}'),
                        _MetricTile(label: 'Memories', value: '${totals['memories'] ?? 0}'),
                        _MetricTile(
                            label: 'Storage',
                            value: humanizeBytes(
                                (totals['storage_bytes'] as num?)?.toInt() ?? 0)),
                        _MetricTile(
                            label: 'New (7d)',
                            value: '${totals['recent_signups_7d'] ?? 0}'),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Align(
                      alignment: Alignment.centerRight,
                      child: OutlinedButton.icon(
                        onPressed: _refreshingStorage ? null : _recalculateStorage,
                        icon: _refreshingStorage
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.refresh),
                        label: const Text('Recalculate storage'),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              _SectionCard(
                title: 'Users',
                icon: Icons.people_outline,
                child: users.isEmpty
                    ? const Text('No users.')
                    : _UserTable(users: users),
              ),
              const SizedBox(height: 16),
              _SectionCard(
                title: 'User search & password reset',
                icon: Icons.search,
                child: _buildSearch(context),
              ),
              const SizedBox(height: 32),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSearch(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextField(
          controller: _searchCtrl,
          onSubmitted: (_) => _search(),
          decoration: InputDecoration(
            labelText: 'Search email / username / name',
            border: const OutlineInputBorder(),
            isDense: true,
            suffixIcon: IconButton(
              icon: _searching
                  ? const SizedBox(
                      width: 16, height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.arrow_forward),
              onPressed: _searching ? null : _search,
            ),
          ),
        ),
        const SizedBox(height: 12),
        if (_results.isEmpty)
          Text('No results.', style: theme.textTheme.bodySmall)
        else
          ..._results.map((u) => _SearchRow(
                user: u,
                busyReset: _resetting.contains(u['id']),
                busyAdmin: _togglingAdmin.contains(u['id']),
                onReset: () => _resetPassword(u),
                onToggleAdmin: () => _toggleAdmin(u),
              )),
      ],
    );
  }
}

// ── Sub-widgets ───────────────────────────────────────────────────────────────

class _MetricTile extends StatelessWidget {
  final String label;
  final String value;
  const _MetricTile({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      width: 130,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(value, style: monoStyle(fontSize: 22, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(label, style: theme.textTheme.bodySmall),
        ],
      ),
    );
  }
}

class _UserTable extends StatelessWidget {
  final List<Map<String, dynamic>> users;
  const _UserTable({required this.users});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        columns: const [
          DataColumn(label: Text('User')),
          DataColumn(label: Text('Provider')),
          DataColumn(label: Text('Signup')),
          DataColumn(label: Text('Projects'), numeric: true),
          DataColumn(label: Text('Activities'), numeric: true),
          DataColumn(label: Text('Memories'), numeric: true),
          DataColumn(label: Text('Storage')),
          DataColumn(label: Text('Encryption')),
        ],
        rows: users.map((u) {
          final tier = u['encryption_tier'] as String? ?? 'none';
          return DataRow(cells: [
            DataCell(Text((u['display_name'] as String?)?.isNotEmpty == true
                ? u['display_name'] as String
                : (u['email'] as String? ?? '#${u['id']}'))),
            DataCell(Text(u['auth_provider'] as String? ?? 'local')),
            DataCell(Text(formatSignup((u['created_at'] as num?) ?? 0))),
            DataCell(Text('${u['project_count'] ?? 0}')),
            DataCell(Text('${u['activity_count'] ?? 0}')),
            DataCell(Text('${u['memory_count'] ?? 0}')),
            DataCell(Text(humanizeBytes((u['storage_bytes'] as num?)?.toInt() ?? 0))),
            DataCell(_TierChip(tier: tier)),
          ]);
        }).toList(),
      ),
    );
  }
}

class _TierChip extends StatelessWidget {
  final String tier;
  const _TierChip({required this.tier});

  @override
  Widget build(BuildContext context) {
    final c = tierColor(tier);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(tier, style: TextStyle(color: c, fontSize: 12)),
    );
  }
}

class _SearchRow extends StatelessWidget {
  final Map<String, dynamic> user;
  final bool busyReset;
  final bool busyAdmin;
  final VoidCallback onReset;
  final VoidCallback onToggleAdmin;

  const _SearchRow({
    required this.user,
    required this.busyReset,
    required this.busyAdmin,
    required this.onReset,
    required this.onToggleAdmin,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tier = user['encryption_tier'] as String? ?? 'none';
    final isAdmin = user['is_admin'] == true;
    // Reset is enabled only for None/Low tiers (server hard-blocks Medium/High).
    final canReset = tier == 'none' || tier == 'low';
    final label = (user['display_name'] as String?)?.isNotEmpty == true
        ? user['display_name'] as String
        : (user['email'] as String? ?? '#${user['id']}');

    final info = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(label, style: theme.textTheme.bodyMedium),
        Text(user['email'] as String? ?? '', style: theme.textTheme.bodySmall),
      ],
    );

    final resetButton = busyReset
        ? const SizedBox(
            width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
        : OutlinedButton(
            onPressed: canReset ? onReset : null,
            child: const Text('Reset password'),
          );

    final adminButton = busyAdmin
        ? const SizedBox(
            width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
        : OutlinedButton(
            onPressed: onToggleAdmin,
            child: Text(isAdmin ? 'Remove admin' : 'Make admin'),
          );

    // A Wrap (not a Row of fixed-width buttons) so on narrow widths the
    // controls reflow onto a second line instead of squeezing `info` to zero.
    final controls = Wrap(
      spacing: 12,
      runSpacing: 8,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        _TierChip(tier: tier),
        adminButton,
        canReset
            ? resetButton
            : Tooltip(
                message:
                    'Blocked: $tier-tier encryption is zero-knowledge. A reset '
                    'would destroy the user\'s encrypted data.',
                child: resetButton,
              ),
      ],
    );

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: LayoutBuilder(
        builder: (context, constraints) {
          // Below this width the controls alone need most of the row, so stack
          // instead of letting `info` get squeezed toward zero width.
          if (constraints.maxWidth >= 560) {
            return Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Expanded(child: info),
                const SizedBox(width: 12),
                controls,
              ],
            );
          }
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [info, const SizedBox(height: 8), controls],
          );
        },
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _ErrorView({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.error_outline, color: kAccent, size: 40),
          const SizedBox(height: 12),
          Text(message),
          const SizedBox(height: 12),
          FilledButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}

// ── Reusable section card (mirrors settings_screen) ──────────────────────────

class _SectionCard extends StatelessWidget {
  final String title;
  final IconData icon;
  final Widget child;

  const _SectionCard({
    required this.title,
    required this.icon,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, color: theme.colorScheme.primary, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(title,
                      style: theme.textTheme.titleLarge,
                      overflow: TextOverflow.ellipsis),
                ),
              ],
            ),
            const Divider(height: 24),
            child,
          ],
        ),
      ),
    );
  }
}

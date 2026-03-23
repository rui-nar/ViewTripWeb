import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/client.dart';
import '../auth/auth_notifier.dart';
import 'projects_notifier.dart';

class ProjectsScreen extends StatefulWidget {
  const ProjectsScreen({super.key});

  @override
  State<ProjectsScreen> createState() => _ProjectsScreenState();
}

class _ProjectsScreenState extends State<ProjectsScreen> {
  final _nameCtrl = TextEditingController();
  bool _stravaConnected = false;
  bool _stravaLoading = false;

  @override
  void initState() {
    super.initState();
    _loadStravaStatus();
    // If the user just returned from the Strava OAuth flow, show a snackbar.
    if (kIsWeb) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final uri = Uri.base;
        if (uri.queryParameters['strava'] == 'connected') {
          _loadStravaStatus();
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Strava connected!')),
          );
        } else if (uri.queryParameters['strava'] == 'error') {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Strava connection failed.')),
          );
        }
      });
    }
  }

  Future<void> _loadStravaStatus() async {
    if (!mounted) return;
    setState(() => _stravaLoading = true);
    try {
      final data = await api.get('/api/strava/status') as Map<String, dynamic>;
      if (mounted) setState(() => _stravaConnected = data['connected'] == true);
    } catch (_) {
      // ignore — status not critical
    } finally {
      if (mounted) setState(() => _stravaLoading = false);
    }
  }

  Future<void> _connectStrava() async {
    try {
      final data = await api.get('/api/strava/connect') as Map<String, dynamic>;
      final url = Uri.parse(data['url'] as String);
      await launchUrl(url, mode: LaunchMode.externalApplication);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not open Strava: $e')),
        );
      }
    }
  }

  Future<void> _disconnectStrava() async {
    try {
      await api.delete('/api/strava/disconnect');
      if (mounted) setState(() => _stravaConnected = false);
    } catch (_) {}
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    super.dispose();
  }

  Future<void> _logout() async {
    await context.read<AuthNotifier>().logout();
    if (mounted) context.go('/login');
  }

  Future<void> _createProject() async {
    final name = _nameCtrl.text.trim();
    if (name.isEmpty) return;
    final notifier = context.read<ProjectsNotifier>();
    await notifier.create(name);
    if (!mounted) return;
    if (notifier.error == null) {
      _nameCtrl.clear();
      final encoded = Uri.encodeComponent(name);
      context.go('/app?project=$encoded');
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final auth = context.watch<AuthNotifier>();

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            Icon(Icons.map_rounded,
                color: theme.colorScheme.primary, size: 22),
            const SizedBox(width: 8),
            const Text('ViewTripWeb'),
          ],
        ),
        actions: [
          // Avatar (Google users)
          if (auth.user?.avatarUrl.isNotEmpty == true)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: CircleAvatar(
                radius: 16,
                backgroundImage: NetworkImage(auth.user!.avatarUrl),
              ),
            ),
          TextButton(
            onPressed: _logout,
            child: const Text('Logout'),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // ── Error banner ──────────────────────────────────────────
                Consumer<ProjectsNotifier>(
                  builder: (_, notifier, __) {
                    if (notifier.error == null) return const SizedBox.shrink();
                    return Container(
                      margin: const EdgeInsets.only(bottom: 16),
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: theme.colorScheme.error.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(8),
                        border:
                            Border.all(color: theme.colorScheme.error),
                      ),
                      child: Text(notifier.error!,
                          style:
                              TextStyle(color: theme.colorScheme.error)),
                    );
                  },
                ),

                // ── New project ───────────────────────────────────────────
                _SectionCard(
                  title: 'New Project',
                  icon: Icons.add_circle_outline,
                  child: Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _nameCtrl,
                          decoration: const InputDecoration(
                              hintText: 'Project name…'),
                          textInputAction: TextInputAction.done,
                          onSubmitted: (_) => _createProject(),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Consumer<ProjectsNotifier>(
                        builder: (_, notifier, __) => ElevatedButton(
                          onPressed:
                              notifier.isLoading ? null : _createProject,
                          style: ElevatedButton.styleFrom(
                              minimumSize: const Size(96, 44)),
                          child: notifier.isLoading
                              ? const SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: Colors.white),
                                )
                              : const Text('Create'),
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 16),

                // ── Open saved ────────────────────────────────────────────
                _SectionCard(
                  title: 'Open Saved',
                  icon: Icons.folder_open_outlined,
                  child: Consumer<ProjectsNotifier>(
                    builder: (_, notifier, __) {
                      if (notifier.isLoading && notifier.projects.isEmpty) {
                        return const Padding(
                          padding: EdgeInsets.symmetric(vertical: 24),
                          child:
                              Center(child: CircularProgressIndicator()),
                        );
                      }
                      if (notifier.projects.isEmpty) {
                        return Padding(
                          padding:
                              const EdgeInsets.symmetric(vertical: 24),
                          child: Center(
                            child: Text('No saved projects yet.',
                                style: theme.textTheme.bodySmall),
                          ),
                        );
                      }
                      return ListView.separated(
                        shrinkWrap: true,
                        physics: const NeverScrollableScrollPhysics(),
                        itemCount: notifier.projects.length,
                        separatorBuilder: (_, __) =>
                            const Divider(height: 1),
                        itemBuilder: (context, i) {
                          final project = notifier.projects[i];
                          final name =
                              project['name'] as String? ?? 'Untitled';
                          return ListTile(
                            contentPadding: const EdgeInsets.symmetric(
                                horizontal: 0, vertical: 4),
                            leading: Icon(Icons.map_outlined,
                                color: theme.colorScheme.primary),
                            title: Text(name,
                                style: theme.textTheme.bodyMedium),
                            trailing: ElevatedButton(
                              onPressed: () {
                                final encoded = Uri.encodeComponent(name);
                                context.go('/app?project=$encoded');
                              },
                              style: ElevatedButton.styleFrom(
                                minimumSize: const Size(72, 36),
                                padding: const EdgeInsets.symmetric(
                                    horizontal: 16),
                              ),
                              child: const Text('Open'),
                            ),
                          );
                        },
                      );
                    },
                  ),
                ),

                const SizedBox(height: 16),

                // ── Import ────────────────────────────────────────────────
                _SectionCard(
                  title: 'Import',
                  icon: Icons.upload_file_outlined,
                  child: Consumer<ProjectsNotifier>(
                    builder: (_, notifier, __) => Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Import a .gettracks file exported from the GetTracks desktop app.',
                          style: theme.textTheme.bodySmall,
                        ),
                        const SizedBox(height: 16),
                        OutlinedButton.icon(
                          onPressed: notifier.isLoading
                              ? null
                              : () async {
                                  final result =
                                      await notifier.importFile();
                                  if (result != null && context.mounted) {
                                    context.go(
                                        '/app?project=${Uri.encodeComponent(result)}');
                                  }
                                },
                          icon: const Icon(Icons.upload_rounded),
                          label: Text(notifier.isLoading
                              ? 'Importing…'
                              : 'Choose .gettracks file'),
                        ),
                      ],
                    ),
                  ),
                ),

                const SizedBox(height: 16),

                // ── Strava ────────────────────────────────────────────────
                _SectionCard(
                  title: 'Strava',
                  icon: Icons.directions_run,
                  child: _stravaLoading
                      ? const Padding(
                          padding: EdgeInsets.symmetric(vertical: 8),
                          child: Center(child: CircularProgressIndicator()),
                        )
                      : Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (_stravaConnected) ...[
                              Row(
                                children: [
                                  Icon(Icons.check_circle,
                                      color: theme.colorScheme.primary,
                                      size: 18),
                                  const SizedBox(width: 8),
                                  Text('Connected',
                                      style: theme.textTheme.bodyMedium),
                                  const Spacer(),
                                  TextButton(
                                    onPressed: _disconnectStrava,
                                    child: const Text('Disconnect'),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(
                                'Open a project and use the sync button in the toolbar to import your Strava activities.',
                                style: theme.textTheme.bodySmall,
                              ),
                            ] else ...[
                              Text(
                                'Connect your Strava account to sync activities directly into a project.',
                                style: theme.textTheme.bodySmall,
                              ),
                              const SizedBox(height: 16),
                              OutlinedButton.icon(
                                onPressed: _connectStrava,
                                icon: const Icon(Icons.link),
                                label: const Text('Connect Strava'),
                              ),
                            ],
                          ],
                        ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ── Reusable section card ─────────────────────────────────────────────────────

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
                Text(title, style: theme.textTheme.titleLarge),
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

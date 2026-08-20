/// First-launch onboarding carousel for native Android/iOS builds — shown
/// once at `/onboarding` before the app ever reaches the login screen (see
/// core/app_router.dart's `authRedirectTarget`). Skip and "Get started" both
/// mark onboarding seen and hand off to `/login`.
library;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../core/onboarding_notifier.dart';

class _OnboardingPage {
  const _OnboardingPage(this.icon, this.title, this.body);
  final IconData icon;
  final String title;
  final String body;
}

// Same feature set as the marketing WelcomeScreen's "Features" section
// (issue: Android launch UX) — a phone-sized subset, four cards.
const _kPages = [
  _OnboardingPage(
    Icons.sync_rounded,
    'One-click Strava sync',
    'OAuth in 30 seconds. Pulls rides, runs and hikes with filters by date '
        'and type — tokens refresh automatically.',
  ),
  _OnboardingPage(
    Icons.location_on_outlined,
    'Pinned memories',
    'Drop a photo, note or video on any point of your route. Memories live '
        'on the timeline and the map.',
  ),
  _OnboardingPage(
    Icons.flight_rounded,
    'Transport gaps, solved',
    'Add a flight, train, bus or ferry between rides — a plausible path '
        'renders on the map, never a straight line through mountains.',
  ),
  _OnboardingPage(
    Icons.download_rounded,
    'One GPX, everywhere',
    'Export the stitched journey as a single GPX for Garmin, Komoot or '
        'RideWithGPS — or self-host the whole thing on your own box.',
  ),
];

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _controller = PageController();
  int _page = 0;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _finish() async {
    await context.read<OnboardingNotifier>().markSeen();
    if (!mounted) return;
    context.go('/login');
  }

  void _next() {
    if (_page == _kPages.length - 1) {
      _finish();
      return;
    }
    _controller.nextPage(
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeInOut,
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final isLastPage = _page == _kPages.length - 1;

    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: isDark
                ? const [Color(0xFF0D1B2A), Color(0xFF1B2838)]
                : const [Color(0xFFF1F5F9), Color(0xFFE2E8F0)],
          ),
        ),
        child: SafeArea(
          child: Column(
            children: [
              Align(
                alignment: Alignment.topRight,
                child: Padding(
                  padding: const EdgeInsets.only(right: 8, top: 4),
                  child: TextButton(
                    onPressed: isLastPage ? null : _finish,
                    child: const Text('Skip'),
                  ),
                ),
              ),
              Expanded(
                child: PageView.builder(
                  controller: _controller,
                  itemCount: _kPages.length,
                  onPageChanged: (i) => setState(() => _page = i),
                  itemBuilder: (context, i) =>
                      _OnboardingPageView(page: _kPages[i], theme: theme),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        for (var i = 0; i < _kPages.length; i++)
                          _Dot(active: i == _page, theme: theme),
                      ],
                    ),
                    const SizedBox(height: 20),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        onPressed: _next,
                        child: Text(isLastPage ? 'Get started' : 'Next'),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _OnboardingPageView extends StatelessWidget {
  const _OnboardingPageView({required this.page, required this.theme});

  final _OnboardingPage page;
  final ThemeData theme;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            width: 96,
            height: 96,
            decoration: BoxDecoration(
              color: theme.colorScheme.primary.withValues(alpha: 0.12),
              shape: BoxShape.circle,
            ),
            child: Icon(page.icon, size: 44, color: theme.colorScheme.primary),
          ),
          const SizedBox(height: 32),
          Text(
            page.title,
            textAlign: TextAlign.center,
            style: theme.textTheme.headlineSmall,
          ),
          const SizedBox(height: 12),
          Text(
            page.body,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
              height: 1.5,
            ),
          ),
        ],
      ),
    );
  }
}

class _Dot extends StatelessWidget {
  const _Dot({required this.active, required this.theme});

  final bool active;
  final ThemeData theme;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      margin: const EdgeInsets.symmetric(horizontal: 4),
      width: active ? 20 : 8,
      height: 8,
      decoration: BoxDecoration(
        color: active
            ? theme.colorScheme.primary
            : theme.colorScheme.primary.withValues(alpha: 0.25),
        borderRadius: BorderRadius.circular(4),
      ),
    );
  }
}

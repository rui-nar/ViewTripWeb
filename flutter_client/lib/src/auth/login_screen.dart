/// Login screen — email/password + Google Sign-In, link to register.
library;

import 'dart:async';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:provider/provider.dart';

// Web-only import: renderButton() from google_sign_in_web.
// Stubbed on non-web platforms via conditional import.
import 'google_button_stub.dart'
    if (dart.library.html) 'google_button_web.dart';

import 'auth_notifier.dart';

const _kWebClientId =
    '544571555396-gj0q3hndadfo00ifotme305jcf4ii5cc.apps.googleusercontent.com';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  final _formKey = GlobalKey<FormState>();
  bool _obscurePassword = true;
  StreamSubscription<GoogleSignInAuthenticationEvent>? _googleSignInSub;

  @override
  void initState() {
    super.initState();
    unawaited(
      GoogleSignIn.instance.initialize(
        // serverClientId must be null on web — GIS reads the client ID from
        // <meta name="google-signin-client_id"> in web/index.html.
        // On Android/iOS it is required to receive an idToken.
        serverClientId: kIsWeb ? null : _kWebClientId,
      ).then((_) {
        _googleSignInSub = GoogleSignIn.instance.authenticationEvents.listen(
          _handleAuthEvent,
          onError: _handleAuthError,
        );
        GoogleSignIn.instance.attemptLightweightAuthentication();
      }),
    );
  }

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    _googleSignInSub?.cancel();
    super.dispose();
  }

  // ── Handlers ──────────────────────────────────────────────────────────────────

  void _handleAuthEvent(GoogleSignInAuthenticationEvent event) {
    if (event is GoogleSignInAuthenticationEventSignIn) {
      _handleGoogleAccount(event.user);
    }
  }

  void _handleAuthError(Object error) {
    if (error is GoogleSignInException &&
        error.code == GoogleSignInExceptionCode.canceled) {
      return;
    }
    _showError('Google sign-in failed: $error');
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    final auth = context.read<AuthNotifier>();
    await auth.loginWithPassword(
      _emailCtrl.text.trim(),
      _passwordCtrl.text,
    );
    if (!mounted) return;
    if (auth.user != null) context.go('/projects');
  }

  /// Called when Google Sign-In produces an account — works for both
  /// renderButton (web) and authenticate() (Android/iOS).
  Future<void> _handleGoogleAccount(GoogleSignInAccount account) async {
    try {
      // authentication is a synchronous getter in v7 (no await needed)
      final idToken = account.authentication.idToken;
      if (idToken == null || idToken.isEmpty) {
        _showError('Google sign-in: no ID token received.');
        return;
      }
      if (!mounted) return;
      final auth = context.read<AuthNotifier>();
      await auth.loginWithGoogle(idToken);
      if (!mounted) return;
      if (auth.user != null) context.go('/projects');
    } catch (e) {
      _showError('Google sign-in failed: $e');
    }
  }

  /// Mobile-only: trigger the native Google account picker.
  Future<void> _mobileGoogleSignIn() async {
    if (!GoogleSignIn.instance.supportsAuthenticate()) return;
    try {
      await GoogleSignIn.instance.authenticate(
        scopeHint: ['email', 'profile', 'openid'],
      );
      // Result delivered via authenticationEvents stream → _handleAuthEvent
    } on GoogleSignInException catch (e) {
      if (e.code == GoogleSignInExceptionCode.canceled) return;
      _showError('Google sign-in failed: $e');
    }
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(msg)));
  }

  // ── Build ─────────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

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
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(32),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      // ── Brand header ──────────────────────────────────────
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.map_rounded,
                              color: theme.colorScheme.primary, size: 28),
                          const SizedBox(width: 10),
                          Text('ViewTrip',
                              style: theme.textTheme.headlineMedium),
                        ],
                      ),
                      const SizedBox(height: 6),
                      Text('Sign in to continue',
                          style: theme.textTheme.bodySmall),
                      const SizedBox(height: 28),

                      // ── Error banner ──────────────────────────────────────
                      Consumer<AuthNotifier>(
                        builder: (_, auth, __) => auth.error == null
                            ? const SizedBox.shrink()
                            : _ErrorBanner(
                                message: auth.error!,
                                onDismiss: auth.clearError,
                              ),
                      ),

                      // ── Form ──────────────────────────────────────────────
                      Form(
                        key: _formKey,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            TextFormField(
                              controller: _emailCtrl,
                              decoration: const InputDecoration(
                                labelText: 'Email or username',
                                prefixIcon: Icon(Icons.person_outline),
                              ),
                              autocorrect: false,
                              textInputAction: TextInputAction.next,
                              validator: (v) =>
                                  (v == null || v.trim().isEmpty)
                                      ? 'Required'
                                      : null,
                            ),
                            const SizedBox(height: 16),
                            TextFormField(
                              controller: _passwordCtrl,
                              decoration: InputDecoration(
                                labelText: 'Password',
                                prefixIcon: const Icon(Icons.lock_outline),
                                suffixIcon: IconButton(
                                  icon: Icon(_obscurePassword
                                      ? Icons.visibility_outlined
                                      : Icons.visibility_off_outlined),
                                  onPressed: () => setState(() =>
                                      _obscurePassword = !_obscurePassword),
                                ),
                              ),
                              obscureText: _obscurePassword,
                              textInputAction: TextInputAction.done,
                              onFieldSubmitted: (_) => _submit(),
                              validator: (v) =>
                                  (v == null || v.isEmpty)
                                      ? 'Required'
                                      : null,
                            ),
                            const SizedBox(height: 24),
                            Consumer<AuthNotifier>(
                              builder: (_, auth, __) => auth.isLoading
                                  ? const SizedBox(
                                      height: 44,
                                      child: Center(
                                          child: CircularProgressIndicator()),
                                    )
                                  : ElevatedButton(
                                      onPressed: _submit,
                                      child: const Text('Sign In'),
                                    ),
                            ),
                          ],
                        ),
                      ),

                      const SizedBox(height: 16),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text("Don't have an account?",
                              style: theme.textTheme.bodySmall),
                          TextButton(
                            onPressed: () => context.go('/register'),
                            child: const Text('Register'),
                          ),
                        ],
                      ),

                      const Divider(height: 32),

                      // ── Google Sign-In ────────────────────────────────────
                      // Web:    Google's own renderButton() (GIS — correct flow)
                      // Mobile: our OutlinedButton calling signIn()
                      kIsWeb
                          ? buildGoogleSignInButton()
                          : Consumer<AuthNotifier>(
                              builder: (_, auth, __) => OutlinedButton.icon(
                                onPressed: auth.isLoading
                                    ? null
                                    : _mobileGoogleSignIn,
                                icon: Image.network(
                                  'https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg',
                                  width: 18,
                                  height: 18,
                                  errorBuilder: (_, __, ___) => const Icon(
                                      Icons.account_circle_outlined,
                                      size: 20),
                                ),
                                label:
                                    const Text('Continue with Google'),
                              ),
                            ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ── Error banner ───────────────────────────────────────────────────────────────

class _ErrorBanner extends StatelessWidget {
  final String message;
  final VoidCallback onDismiss;
  const _ErrorBanner({required this.message, required this.onDismiss});

  @override
  Widget build(BuildContext context) {
    final color = Theme.of(context).colorScheme.error;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color),
      ),
      child: Row(
        children: [
          Icon(Icons.error_outline, color: color, size: 18),
          const SizedBox(width: 8),
          Expanded(
              child:
                  Text(message, style: TextStyle(color: color, fontSize: 13))),
          GestureDetector(
              onTap: onDismiss,
              child: Icon(Icons.close, color: color, size: 16)),
        ],
      ),
    );
  }
}

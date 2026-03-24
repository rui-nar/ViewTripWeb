/// Stub for non-web platforms — renderButton is never called on mobile
/// (the login_screen uses a regular OutlinedButton instead).
library;

import 'package:flutter/material.dart';

Widget buildGoogleSignInButton() => const SizedBox.shrink();

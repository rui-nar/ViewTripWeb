// This file is only ever compiled for web (conditional import), so dart:html is
// the right tool here.
// ignore_for_file: deprecated_member_use, avoid_web_libraries_in_flutter
import 'dart:html' as html;

/// Hard-reload the page so the browser fetches the freshly-deployed bundle.
void reloadApp() => html.window.location.reload();

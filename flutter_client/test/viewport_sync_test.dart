// Unit tests for viewportSyncPath — the pure lat/lng/zoom → query-string
// builder behind the debounced camera→URL sync (issue #76 follow-up). No
// live MapController needed.

import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/projects/viewport_sync.dart';

void main() {
  test('builds the /app path with project + camera query params', () {
    final path = viewportSyncPath(
      basePath: '/app',
      projectName: 'Trip',
      lat: 45.5,
      lng: 6.25,
      zoom: 12.0,
    );
    expect(path, '/app?project=Trip&lat=45.5&lng=6.25&zoom=12.0');
  });

  test('builds the /view path (mirrors app_screen.dart for view_screen.dart)',
      () {
    final path = viewportSyncPath(
      basePath: '/view',
      projectName: 'Trip',
      lat: -10.0,
      lng: 160.0,
      zoom: 8.5,
    );
    expect(path, '/view?project=Trip&lat=-10.0&lng=160.0&zoom=8.5');
  });

  test('URL-encodes the project name', () {
    final path = viewportSyncPath(
      basePath: '/app',
      projectName: 'Alps & Dolomites',
      lat: 46.0,
      lng: 11.0,
      zoom: 9.0,
    );
    expect(
      path,
      '/app?project=Alps%20%26%20Dolomites&lat=46.0&lng=11.0&zoom=9.0',
    );
  });
}

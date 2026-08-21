/// Pure helper for debounced map-camera → URL query-param sync (issue #76
/// follow-up): keeps `lat`/`lng`/`zoom` in the browser URL as the user pans
/// so a forced reload (the JS backstop added for the black-screen bug) or a
/// normal browser refresh restores the viewport via the existing
/// `initialLat`/`initialLng`/`initialZoom` route params.
library;

import 'package:flutter_map/flutter_map.dart'
    show MapEvent, MapEventNonRotatedSizeChange;

/// Whether [event] carries a camera position worth writing to the URL.
///
/// A size change — the map's first layout, or the elevation chart swapping its
/// loading placeholder for the real chart — leaves the camera exactly where it
/// was, so there is nothing to sync. Syncing on one is actively harmful: it
/// stamps the *default* viewport into the URL while the project is still
/// loading, and `lat`/`lng`/`zoom` on the route means "the user arrived with an
/// explicit viewport", which suppresses the fit-to-bounds animation that should
/// run once the tracks land.
bool shouldSyncViewport(MapEvent event) =>
    event is! MapEventNonRotatedSizeChange;

/// Builds the `/app` or `/view` route location for [projectName] with the
/// given camera position encoded as query params. No live `MapController`
/// required, so this is independently unit-testable. [ownerId] (issue #106)
/// is included so a reload of a shared project's URL still resolves it.
///
/// [lat]/[lng]/[zoom] are optional: pass all three when a camera position
/// was actually available, or omit them (e.g. the map hasn't attached yet —
/// issue #219) to link to the project without a saved viewport; the
/// destination screen falls back to its default center/fit-bounds.
String viewportSyncPath({
  required String basePath,
  required String projectName,
  int? ownerId,
  double? lat,
  double? lng,
  double? zoom,
}) {
  return '$basePath?project=${Uri.encodeComponent(projectName)}'
      '${ownerId != null ? '&owner=$ownerId' : ''}'
      '${lat != null && lng != null && zoom != null ? '&lat=$lat&lng=$lng&zoom=$zoom' : ''}';
}

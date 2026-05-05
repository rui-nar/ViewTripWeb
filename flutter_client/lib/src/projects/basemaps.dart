/// Basemap tile URL constants shared between manage, view, and share screens.
library;

// ── Provider flag ──────────────────────────────────────────────────────────────
// Toggle via --dart-define=BASEMAP_PROVIDER=ESRI (default MAPBOX).
const _kProvider =
    String.fromEnvironment('BASEMAP_PROVIDER', defaultValue: 'MAPBOX');
const kUseMapbox = _kProvider == 'MAPBOX';

// ── Mapbox ─────────────────────────────────────────────────────────────────────
const kMapboxToken = String.fromEnvironment('MAPBOX_TOKEN');

/// Mapbox satellite-streets — satellite imagery + labels in one layer.
/// Used in view / share / export mode (raster tile path).
const kMapboxViewUrl =
    'https://api.mapbox.com/styles/v1/mapbox/satellite-v9/tiles/256/{z}/{x}/{y}'
    '?access_token=$kMapboxToken';

/// Mapbox outdoors — labelled street/terrain map for manage mode (raster tile path).
const kMapboxManageUrl =
    'https://api.mapbox.com/styles/v1/mapbox/outdoors-v12/tiles/256/{z}/{x}/{y}'
    '?access_token=$kMapboxToken';

/// Mapbox satellite-streets vector style — satellite imagery + vector labels.
/// Used in view / share mode (vector tile path via VectorTileLayer).
/// {key} is replaced at runtime by StyleUriMapper with kMapboxToken.
const kMapboxViewStyleUri =
    'mapbox://styles/mapbox/satellite-streets-v12?access_token={key}';

/// Mapbox outdoors vector style — terrain + streets for manage mode.
/// Used in manage mode (vector tile path via VectorTileLayer).
/// {key} is replaced at runtime by StyleUriMapper with kMapboxToken.
const kMapboxManageStyleUri =
    'mapbox://styles/mapbox/outdoors-v12?access_token={key}';

// ── Esri (legacy, kept for fallback via BASEMAP_PROVIDER=ESRI) ─────────────────

/// CartoDB Voyager — labelled street/terrain map; used in manage mode.
/// Requires [kManageBasemapSubdomains] in the TileLayer `subdomains` param.
const kManageBasemapUrl =
    'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png';
const kManageBasemapSubdomains = ['a', 'b', 'c', 'd'];

/// Esri World Imagery — satellite; used in view and share mode.
const kViewBasemapUrl =
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

/// Esri World Boundaries and Places — transparent label/border overlay.
/// Stack on top of [kViewBasemapUrl] to add city names, country borders, etc.
const kViewLabelsUrl =
    'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}';

/// CartoDB labels-only overlay — country names, capitals, major cities on a
/// transparent background. No streets. Stacked on top of satellite in Mapbox mode.
/// @2x retina tiles (512 px) — use with tileSize:512 + zoomOffset:1 for crisp,
/// smaller labels.
const kCartoDblLabelsUrl =
    'https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}@2x.png';
const kCartoDblLabelsSubdomains = ['a', 'b', 'c', 'd'];

// ── Resolved raster URLs (consumed by all screens) ────────────────────────────

const kActiveViewBasemapUrl =
    kUseMapbox ? kMapboxViewUrl : kViewBasemapUrl;

/// Labels overlay stacked on top of the satellite basemap (raster path only).
const String kActiveViewLabelsUrl = kViewLabelsUrl;

const List<String> kActiveViewLabelsSubdomains =
    kUseMapbox ? kCartoDblLabelsSubdomains : [];

const kActiveManageBasemapUrl =
    kUseMapbox ? kMapboxManageUrl : kManageBasemapUrl;

const List<String> kActiveManageSubdomains =
    kUseMapbox ? [] : kManageBasemapSubdomains;

// ── Resolved vector style URIs (null when ESRI provider is selected) ──────────

/// Mapbox vector style URI for view / share mode.
/// Null when using the ESRI raster fallback.
const String? kActiveViewStyleUri =
    kUseMapbox ? kMapboxViewStyleUri : null;

/// Mapbox vector style URI for manage mode.
/// Null when using the ESRI raster fallback.
const String? kActiveManageStyleUri =
    kUseMapbox ? kMapboxManageStyleUri : null;

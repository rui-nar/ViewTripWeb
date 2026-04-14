/// Basemap tile URL constants shared between manage, view, and share screens.
library;

// ── Provider flag ──────────────────────────────────────────────────────────────
// Toggle via --dart-define=BASEMAP_PROVIDER=ESRI (default MAPBOX).
const _kProvider =
    String.fromEnvironment('BASEMAP_PROVIDER', defaultValue: 'MAPBOX');
const kUseMapbox = _kProvider == 'MAPBOX';

// ── Mapbox ─────────────────────────────────────────────────────────────────────
const _kMapboxToken = String.fromEnvironment('MAPBOX_TOKEN');

/// Mapbox satellite-streets — satellite imagery + labels in one layer.
/// Used in view / share / export mode.
const kMapboxViewUrl =
    'https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12/tiles/256/{z}/{x}/{y}@2x'
    '?access_token=$_kMapboxToken';

/// Mapbox streets — labelled street/terrain map for manage mode.
const kMapboxManageUrl =
    'https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256/{z}/{x}/{y}@2x'
    '?access_token=$_kMapboxToken';

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

// ── Resolved URLs (consumed by all screens) ────────────────────────────────────

const kActiveViewBasemapUrl =
    kUseMapbox ? kMapboxViewUrl : kViewBasemapUrl;

/// Null when Mapbox is active (labels are baked into the satellite-streets style).
const String? kActiveViewLabelsUrl =
    kUseMapbox ? null : kViewLabelsUrl;

const kActiveManageBasemapUrl =
    kUseMapbox ? kMapboxManageUrl : kManageBasemapUrl;

const List<String> kActiveManageSubdomains =
    kUseMapbox ? [] : kManageBasemapSubdomains;

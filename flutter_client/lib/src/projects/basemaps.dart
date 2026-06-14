/// Basemap tile URL constants shared between manage, view, and share screens.
library;

// ── Zoom bounds ──────────────────────────────────────────────────────────────
/// Hard upper bound for the interactive map camera zoom.
///
/// vector_map_tiles' internal `_ZoomScaler` precomputes a scale table for zoom
/// levels 0..23 (a fixed 24-entry list) and indexes it directly by tile zoom,
/// with no clamping. In vector mode the layer's `maximumZoom` is NOT applied to
/// the camera, so without a `MapOptions.maxZoom` a pinch gesture can drive the
/// camera (hence the tile zoom = floor(cameraZoom + offset)) past 23 and crash
/// with a RangeError. Capping the camera below that limit prevents it.
/// Must stay < 24; 22 also matches our raster `maxNativeZoom`.
const double kMaxMapZoom = 22;

// ── Provider flag ──────────────────────────────────────────────────────────────
// Toggle via --dart-define=BASEMAP_PROVIDER=ESRI (default MAPBOX).
const _kProvider =
    String.fromEnvironment('BASEMAP_PROVIDER', defaultValue: 'MAPBOX');
const kUseMapbox = _kProvider == 'MAPBOX';

// ── Mapbox ─────────────────────────────────────────────────────────────────────
const kMapboxToken = String.fromEnvironment('MAPBOX_TOKEN');

/// Mapbox Styles API raster tiles for the custom satellite style.
/// Used in view / share mode. Labels are baked into the style tiles, so no
/// separate labels overlay is needed (see kActiveViewLabelsOverlayUrl).
/// RetinaMode in TileLayer fetches zoom+1 tiles on high-DPI screens → sharp.
const kMapboxViewUrl =
    'https://api.mapbox.com/styles/v1/port82/cmot5rk5l007301sfe4g2fyqz/tiles/256/{z}/{x}/{y}'
    '?access_token=$kMapboxToken';

/// Mapbox outdoors — labelled street/terrain map for manage mode (raster tile path).
const kMapboxManageUrl =
    'https://api.mapbox.com/styles/v1/mapbox/outdoors-v12/tiles/256/{z}/{x}/{y}'
    '?access_token=$kMapboxToken';

/// Mapbox satellite-streets vector style — satellite imagery + vector labels.
/// Used in view / share mode (vector tile path via VectorTileLayer).
/// {key} is replaced at runtime by StyleUriMapper with kMapboxToken.
//const kMapboxViewStyleUri =
//    'mapbox://styles/mapbox/satellite-streets-v12?access_token={key}';
const kMapboxViewStyleUri = 'mapbox://styles/port82/cmot5rk5l007301sfe4g2fyqz?access_token={key}';
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

/// Labels overlay for the VIEW map raster path.
/// Null when Mapbox is selected: the Mapbox Styles API tiles already bake
/// labels into the rendered PNG — a separate overlay would double them.
const String? kActiveViewLabelsOverlayUrl = kUseMapbox ? null : kViewLabelsUrl;

const List<String> kActiveViewLabelsSubdomains =
    kUseMapbox ? kCartoDblLabelsSubdomains : [];

const kActiveManageBasemapUrl =
    kUseMapbox ? kMapboxManageUrl : kManageBasemapUrl;

const List<String> kActiveManageSubdomains =
    kUseMapbox ? [] : kManageBasemapSubdomains;

// ── Resolved vector style URIs (null when ESRI provider is selected) ──────────

/// Mapbox vector style URI for view / share mode.
/// Intentionally null: the satellite view uses the Mapbox Styles API raster
/// tile endpoint (kMapboxViewUrl) with RetinaMode instead of VectorTileLayer.
/// VectorTileLayer hardcodes 256 px tiles with no override → blurry on HiDPI.
/// Raster TileLayer + RetinaMode.isHighDensity requests zoom+1 tiles → sharp.
const String? kActiveViewStyleUri = null;

/// Mapbox vector style URI for manage mode.
/// Null when using the ESRI raster fallback.
const String? kActiveManageStyleUri =
    kUseMapbox ? kMapboxManageStyleUri : null;

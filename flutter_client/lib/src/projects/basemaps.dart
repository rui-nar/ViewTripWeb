/// Basemap tile URL constants shared between manage, view, and share screens.
library;

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

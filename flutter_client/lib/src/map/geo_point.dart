/// Plain coordinate type — no map-library dependency.
library;

/// A geographic point as a named Dart record.
/// Use this in non-map code; convert to [LatLng] only at map rendering sites.
typedef GeoPoint = ({double lat, double lon});

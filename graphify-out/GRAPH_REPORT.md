# Graph Report - flutter_client/lib  (2026-04-28)

## Corpus Check
- Corpus is ~39,893 words - fits in a single context window. You may not need a graph.

## Summary
- 582 nodes · 675 edges · 20 communities detected
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Welcome Screen & Design Tokens|Welcome Screen & Design Tokens]]
- [[_COMMUNITY_App Import Hub|App Import Hub]]
- [[_COMMUNITY_Map Geometry & Track Data|Map Geometry & Track Data]]
- [[_COMMUNITY_API Client & HTTP Layer|API Client & HTTP Layer]]
- [[_COMMUNITY_Activity Panel & Day Editor|Activity Panel & Day Editor]]
- [[_COMMUNITY_Auth State & Forms|Auth State & Forms]]
- [[_COMMUNITY_Memory Dialog|Memory Dialog]]
- [[_COMMUNITY_Location Picker Dialog|Location Picker Dialog]]
- [[_COMMUNITY_Project Stats Screen|Project Stats Screen]]
- [[_COMMUNITY_Settings Screen|Settings Screen]]
- [[_COMMUNITY_Day Metadata Editor|Day Metadata Editor]]
- [[_COMMUNITY_Projects List Screen|Projects List Screen]]
- [[_COMMUNITY_Map Panel|Map Panel]]
- [[_COMMUNITY_Memory Detail Modal|Memory Detail Modal]]
- [[_COMMUNITY_Strava Import Screen|Strava Import Screen]]
- [[_COMMUNITY_Project Settings Dialog|Project Settings Dialog]]
- [[_COMMUNITY_Login Screen|Login Screen]]
- [[_COMMUNITY_App Entry & Routing|App Entry & Routing]]
- [[_COMMUNITY_Theme & Auth Plugins|Theme & Auth Plugins]]
- [[_COMMUNITY_Basemap Config|Basemap Config]]

## God Nodes (most connected - your core abstractions)
1. `package:flutter/material.dart` - 28 edges
2. `package:provider/provider.dart` - 12 edges
3. `package:go_router/go_router.dart` - 11 edges
4. `../api/client.dart` - 11 edges
5. `project_notifier.dart` - 11 edges
6. `package:flutter/foundation.dart` - 9 edges
7. `package:latlong2/latlong.dart` - 8 edges
8. `package:flutter_map/flutter_map.dart` - 7 edges
9. `../auth/auth_notifier.dart` - 6 edges
10. `package:http/http.dart` - 4 edges

## Surprising Connections (you probably didn't know these)
- None detected - all connections are within the same source files.

## Communities

### Community 0 - "Welcome Screen & Design Tokens"
Cohesion: 0.03
Nodes (62): build, Center, Color, Column, Container, _dashedLine, _dot, _ElevationStrip (+54 more)

### Community 1 - "App Import Hub"
Cohesion: 0.04
Nodes (54): activity_panel.dart, basemaps.dart, dart:html, dart:ui, elevation_chart.dart, AuthService, _persist, AppScreen (+46 more)

### Community 2 - "Map Geometry & Track Data"
Cohesion: 0.04
Nodes (45): dart:math, LatLng, toLatLng, _haversineKm, LatLng, build, _compute, didUpdateWidget (+37 more)

### Community 3 - "API Client & HTTP Layer"
Cohesion: 0.05
Nodes (40): ../api/client.dart, auth_service.dart, dart:convert, dart:io, ApiClient, ApiException, clearToken, _handle (+32 more)

### Community 4 - "Activity Panel & Day Editor"
Cohesion: 0.05
Nodes (42): ../core/design_tokens.dart, day_meta_editor.dart, _ActivityIconBox, ActivityPanel, _ActivityPanelState, _addNew, AlertDialog, _apply (+34 more)

### Community 5 - "Auth State & Forms"
Cohesion: 0.06
Nodes (34): ../auth/auth_notifier.dart, ../auth/login_screen.dart, auth_notifier.dart, ../auth/register_screen.dart, ../auth/welcome_screen.dart, build, Container, dispose (+26 more)

### Community 6 - "Memory Dialog"
Cohesion: 0.06
Nodes (34): AlertDialog, build, dispose, _fmtDate, _fmtTime, initState, MemoryDialog, _MemoryDialogState (+26 more)

### Community 7 - "Location Picker Dialog"
Cohesion: 0.06
Nodes (31): build, Dialog, dispose, Icon, initState, LatLng, LocationPickerDialog, _LocationPickerDialogState (+23 more)

### Community 8 - "Project Stats Screen"
Cohesion: 0.08
Nodes (23): build, _capitalize, Card, Center, _CountRow, Divider, _fmtDate, _fmtDistance (+15 more)

### Community 9 - "Settings Screen"
Cohesion: 0.09
Nodes (21): ../auth/auth_service.dart, dart:js_interop, AuthService, build, Card, dispose, Divider, _extractDetail (+13 more)

### Community 10 - "Day Metadata Editor"
Cohesion: 0.09
Nodes (21): _addTag, _applyMeta, _applyMetaNoJournal, build, Column, _DayMetaDialogWrapper, _DayMetaDialogWrapperState, DayMetaEditor (+13 more)

### Community 11 - "Projects List Screen"
Cohesion: 0.09
Nodes (21): _BgPainter, build, Card, Column, Container, dispose, Divider, Icon (+13 more)

### Community 12 - "Map Panel"
Cohesion: 0.1
Nodes (20): _alternateColor, build, Center, didUpdateWidget, dispose, _fitBoundsOnce, _iconForSegmentType, initState (+12 more)

### Community 13 - "Memory Detail Modal"
Cohesion: 0.1
Nodes (19): build, Dialog, dispose, _fmtDate, Function, Icon, initState, _MemoryDetailModal (+11 more)

### Community 14 - "Strava Import Screen"
Cohesion: 0.1
Nodes (19): _ActivityTile, _ActivityTileState, build, Center, FilterChip, _fmtDay, _formatDate, initState (+11 more)

### Community 15 - "Project Settings Dialog"
Cohesion: 0.11
Nodes (18): _addOption, AlertDialog, alternateColor, build, _colorPreview, dispose, Divider, _fmtDate (+10 more)

### Community 16 - "Login Screen"
Cohesion: 0.12
Nodes (16): dart:async, build, Container, dispose, Divider, _ErrorBanner, _handleAuthError, _handleAuthEvent (+8 more)

### Community 17 - "App Entry & Routing"
Cohesion: 0.12
Nodes (15): build, main, ViewTripApp, _ViewTripAppState, package:flutter_web_plugins/url_strategy.dart, package:google_sign_in/google_sign_in.dart, src/auth/auth_notifier.dart, src/auth/auth_service.dart (+7 more)

### Community 18 - "Theme & Auth Plugins"
Cohesion: 0.15
Nodes (9): buildGoogleSignInButton, buildGoogleSignInButton, SizedBox, TextStyle, ThemeNotifier, package:flutter/material.dart, package:google_fonts/google_fonts.dart, package:google_sign_in_web/web_only.dart (+1 more)

### Community 19 - "Basemap Config"
Cohesion: 1.0
Nodes (0): 

## Knowledge Gaps
- **509 isolated node(s):** `ViewTripApp`, `_ViewTripAppState`, `main`, `build`, `package:flutter_web_plugins/url_strategy.dart` (+504 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Basemap Config`** (1 nodes): `basemaps.dart`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `package:flutter/material.dart` connect `Theme & Auth Plugins` to `Welcome Screen & Design Tokens`, `App Import Hub`, `Map Geometry & Track Data`, `Activity Panel & Day Editor`, `Auth State & Forms`, `Memory Dialog`, `Location Picker Dialog`, `Project Stats Screen`, `Settings Screen`, `Day Metadata Editor`, `Projects List Screen`, `Map Panel`, `Memory Detail Modal`, `Strava Import Screen`, `Project Settings Dialog`, `Login Screen`, `App Entry & Routing`?**
  _High betweenness centrality (0.589) - this node is a cross-community bridge._
- **Why does `../api/client.dart` connect `API Client & HTTP Layer` to `App Import Hub`, `Map Geometry & Track Data`, `Memory Dialog`, `Location Picker Dialog`, `Settings Screen`, `Memory Detail Modal`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Why does `project_notifier.dart` connect `Memory Dialog` to `App Import Hub`, `Activity Panel & Day Editor`, `Day Metadata Editor`, `Map Panel`, `Memory Detail Modal`, `Strava Import Screen`, `Project Settings Dialog`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **What connects `ViewTripApp`, `_ViewTripAppState`, `main` to the rest of the system?**
  _509 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Welcome Screen & Design Tokens` be split into smaller, more focused modules?**
  _Cohesion score 0.03 - nodes in this community are weakly interconnected._
- **Should `App Import Hub` be split into smaller, more focused modules?**
  _Cohesion score 0.04 - nodes in this community are weakly interconnected._
- **Should `Map Geometry & Track Data` be split into smaller, more focused modules?**
  _Cohesion score 0.04 - nodes in this community are weakly interconnected._
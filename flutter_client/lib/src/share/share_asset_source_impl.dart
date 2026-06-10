/// Production [ShareAssetSource] — renders the trip map via the offscreen
/// exporter and fetches memory photo bytes over authenticated HTTP.
library;

import 'dart:typed_data';

import 'package:flutter/widgets.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:http/http.dart' as http;

import '../projects/image_export.dart';
import '../projects/project_notifier.dart';
import 'share_day_bounds.dart';
import 'share_interfaces.dart';

class ShareAssetSourceImpl implements ShareAssetSource {
  final ProjectNotifier notifier;

  /// Provides a live BuildContext at render time (the share dialog's context),
  /// required by the offscreen exporter for the Overlay + MediaQuery.
  final BuildContext Function() contextProvider;

  const ShareAssetSourceImpl(this.notifier, this.contextProvider);

  @override
  Future<Uint8List?> renderMapImage(
      {required bool dayFocus, String? date}) async {
    LatLngBounds? bounds;
    if (dayFocus && date != null) {
      final points = dayRoutePoints(
        geo: notifier.geo,
        items: notifier.items,
        activities: notifier.activities,
        date: date,
      );
      if (points.isNotEmpty) bounds = LatLngBounds.fromPoints(points);
    }
    return performOffscreenExport(
      context: contextProvider(),
      notifier: notifier,
      projectName: notifier.projectName ?? 'trip',
      opts: const ImageExportOptions(includeChart: false, includeTitle: false),
      boundsOverride: bounds,
    );
  }

  @override
  Future<List<Uint8List>> fetchPhotos(int memoryId, List<String> uuids) async {
    final headers = notifier.photoAuthHeaders;
    final out = <Uint8List>[];
    for (final uuid in uuids) {
      final url = notifier.photoFullUrl(memoryId.toString(), uuid);
      try {
        final res = await http.get(Uri.parse(url), headers: headers);
        if (res.statusCode >= 200 && res.statusCode < 300) {
          out.add(res.bodyBytes);
        }
      } catch (_) {
        // Skip a photo that fails to download rather than aborting the share.
      }
    }
    return out;
  }
}

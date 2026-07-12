/// Config dialog for the A0 poster export (issue #14, unit F). Mirrors
/// [ImageExportDialog] in `image_export.dart`: an `AlertDialog` with one
/// `CheckboxListTile` per config field, confirming pops the dialog and
/// invokes a callback with an options object.
library;

import 'package:flutter/material.dart';

/// One checkbox per field of `PosterConfigIn` in `api/poster.py`. Defaults
/// favour the most broadly useful sections (distance/elevation/hero photo/
/// memory text/counters) on, and the more niche or heavier ones (all photos,
/// tag pie chart, encounters) off.
class PosterConfigOptions {
  final bool distance;
  final bool elevation;
  final bool heroPhoto;
  final bool allPhotos;
  final bool memoryText;
  final bool counters;
  final bool tagPie;
  final bool encounters;

  const PosterConfigOptions({
    required this.distance,
    required this.elevation,
    required this.heroPhoto,
    required this.allPhotos,
    required this.memoryText,
    required this.counters,
    required this.tagPie,
    required this.encounters,
  });

  /// Matches `PosterConfigIn`'s field names in `api/poster.py`.
  Map<String, bool> toJson() => {
        'distance': distance,
        'elevation': elevation,
        'hero_photo': heroPhoto,
        'all_photos': allPhotos,
        'memory_text': memoryText,
        'counters': counters,
        'tag_pie': tagPie,
        'encounters': encounters,
      };
}

class PosterConfigDialog extends StatefulWidget {
  final void Function(PosterConfigOptions) onConfirm;
  const PosterConfigDialog({super.key, required this.onConfirm});

  @override
  State<PosterConfigDialog> createState() => _PosterConfigDialogState();
}

class _PosterConfigDialogState extends State<PosterConfigDialog> {
  bool _distance = true;
  bool _elevation = true;
  bool _heroPhoto = true;
  bool _allPhotos = false;
  bool _memoryText = true;
  bool _counters = true;
  bool _tagPie = false;
  bool _encounters = false;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Generate poster'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            CheckboxListTile(
              title: const Text('Distance'),
              value: _distance,
              onChanged: (v) => setState(() => _distance = v!),
              contentPadding: EdgeInsets.zero,
              dense: true,
            ),
            CheckboxListTile(
              title: const Text('Elevation'),
              value: _elevation,
              onChanged: (v) => setState(() => _elevation = v!),
              contentPadding: EdgeInsets.zero,
              dense: true,
            ),
            CheckboxListTile(
              title: const Text('Hero photo'),
              value: _heroPhoto,
              onChanged: (v) => setState(() => _heroPhoto = v!),
              contentPadding: EdgeInsets.zero,
              dense: true,
            ),
            CheckboxListTile(
              title: const Text('All photos'),
              value: _allPhotos,
              onChanged: (v) => setState(() => _allPhotos = v!),
              contentPadding: EdgeInsets.zero,
              dense: true,
            ),
            CheckboxListTile(
              title: const Text('Memory text'),
              value: _memoryText,
              onChanged: (v) => setState(() => _memoryText = v!),
              contentPadding: EdgeInsets.zero,
              dense: true,
            ),
            CheckboxListTile(
              title: const Text('Counters'),
              value: _counters,
              onChanged: (v) => setState(() => _counters = v!),
              contentPadding: EdgeInsets.zero,
              dense: true,
            ),
            CheckboxListTile(
              title: const Text('Tag pie chart'),
              value: _tagPie,
              onChanged: (v) => setState(() => _tagPie = v!),
              contentPadding: EdgeInsets.zero,
              dense: true,
            ),
            CheckboxListTile(
              title: const Text('Number of encounters'),
              value: _encounters,
              onChanged: (v) => setState(() => _encounters = v!),
              contentPadding: EdgeInsets.zero,
              dense: true,
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () {
            final opts = PosterConfigOptions(
              distance: _distance,
              elevation: _elevation,
              heroPhoto: _heroPhoto,
              allPhotos: _allPhotos,
              memoryText: _memoryText,
              counters: _counters,
              tagPie: _tagPie,
              encounters: _encounters,
            );
            Navigator.of(context).pop();
            widget.onConfirm(opts);
          },
          child: const Text('Generate'),
        ),
      ],
    );
  }
}

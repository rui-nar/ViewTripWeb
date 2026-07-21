/// Controller for the [ActivityEditorPage] — owns the editable [TrackEditModel]
/// plus tool state (active tool, selected vertex, trim range) and exposes the
/// edit operations the page's gestures drive.
///
/// Kept as a plain [ChangeNotifier] with no widget dependencies so every tool
/// interaction and the resulting point list / save payload are unit-testable,
/// mirroring the day-meta editor's separation of state from rendering.
library;

import 'package:flutter/foundation.dart';

import 'track_edit_model.dart';

/// The active editing tool.
enum EditTool { trim, add, remove, split }

class TrackEditorController extends ChangeNotifier {
  final TrackEditModel model;

  TrackEditorController(this.model) {
    _trimEnd = model.length > 0 ? model.length - 1 : 0;
  }

  EditTool _tool = EditTool.trim;
  EditTool get tool => _tool;
  set tool(EditTool t) {
    if (_tool == t) return;
    _tool = t;
    _selectedIndex = null;
    notifyListeners();
  }

  /// Currently selected vertex index (Remove / Split), or null.
  int? _selectedIndex;
  int? get selectedIndex => _selectedIndex;

  /// Inclusive trim range [start..end]; null until the user adjusts a handle.
  int _trimStart = 0;
  int _trimEnd = 0;
  int get trimStart => _trimStart;
  int get trimEnd => _trimEnd;

  bool get isDirty => model.isDirty;
  bool get canSave => model.isDirty && model.isValid;

  List<EditPoint> get points => model.points;

  // ── Selection ──────────────────────────────────────────────────────────────

  void selectVertex(int? index) {
    if (_selectedIndex == index) return;
    _selectedIndex = index;
    notifyListeners();
  }

  // ── Trim ─────────────────────────────────────────────────────────────────

  /// Set the trim window's start handle (clamped below the end handle).
  void setTrimStart(int index) {
    _trimStart = index.clamp(0, _trimEnd);
    notifyListeners();
  }

  /// Set the trim window's end handle (clamped above the start handle).
  void setTrimEnd(int index) {
    _trimEnd = index.clamp(_trimStart, model.length - 1);
    notifyListeners();
  }

  /// Apply the current trim window, dropping points outside [trimStart..trimEnd].
  void applyTrim() {
    model.trim(_trimStart, _trimEnd);
    _trimStart = 0;
    _trimEnd = model.length - 1;
    _selectedIndex = null;
    notifyListeners();
  }

  /// Trim to keep points [index]..end (context-menu "keep from here").
  void trimFrom(int index) {
    setTrimStart(index);
    applyTrim();
  }

  /// Trim to keep points 0..[index] (context-menu "keep up to here").
  void trimTo(int index) {
    setTrimEnd(index);
    applyTrim();
  }

  // ── Add / Remove / Move ────────────────────────────────────────────────────

  /// Insert [point] into the segment after vertex [index] (-1 to prepend).
  void addPointAfter(int index, EditPoint point) {
    model.addPointAfter(index, point);
    notifyListeners();
  }

  /// Remove the vertex at [index] (defaults to the current selection).
  void removeSelected([int? index]) {
    final i = index ?? _selectedIndex;
    if (i == null) return;
    model.removePoint(i);
    _selectedIndex = null;
    notifyListeners();
  }

  /// Reshape: move vertex [index] to a new position.
  void moveVertex(int index, double lat, double lng) {
    model.movePoint(index, lat, lng);
    notifyListeners();
  }

  // ── Split ──────────────────────────────────────────────────────────────────

  /// Whether [index] is a valid split boundary (two non-trivial pieces).
  bool canSplitAt(int index) => index >= 1 && index <= model.length - 2;

  /// Whether [index] is a valid boundary for "cut & insert transport" (#104):
  /// like [canSplitAt], but the tail also loses its shared boundary point, so
  /// it needs one extra point to stay non-trivial.
  bool canCutForTransport(int index) => index >= 1 && index <= model.length - 3;

  /// Preview head/tail lists for a split at [index]; throws if not valid.
  ({List<EditPoint> head, List<EditPoint> tail}) previewSplit(int index) =>
      model.previewSplit(index);

  // ── Save payload ───────────────────────────────────────────────────────────

  Map<String, dynamic> toSavePayload() => model.toSavePayload();
}

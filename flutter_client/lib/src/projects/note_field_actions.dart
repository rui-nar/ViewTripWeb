/// Copy/paste buttons for a notes field (issue #175).
///
/// On mobile web the engine's own text-selection toolbar is unreliable —
/// CanvasKit paints text into a canvas, so long-press selection is the engine's
/// rather than the browser's, and `Clipboard.getData` maps to
/// `navigator.clipboard.readText()`, which iOS Safari does not grant to a page.
/// The result is notes fields you cannot cut, copy or paste from.
///
/// These buttons bypass that path entirely: they act on the field's controller
/// and fire from a real tap, which is the user activation `writeText()` wants.
/// Paste can still be refused by the browser — say so rather than doing nothing.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Inserts [pasted] into [value] at the cursor, replacing any selection, and
/// leaves the cursor after the inserted text. Pure, so it is testable without a
/// clipboard: an invalid/absent selection appends.
TextEditingValue applyPaste(TextEditingValue value, String pasted) {
  final selection = value.selection;
  if (!selection.isValid) {
    final text = value.text + pasted;
    return TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: text.length),
    );
  }
  final text = value.text.replaceRange(selection.start, selection.end, pasted);
  return TextEditingValue(
    text: text,
    selection: TextSelection.collapsed(offset: selection.start + pasted.length),
  );
}

/// Compact copy + paste buttons for the notes field driven by [controller].
///
/// Mount as an [InputDecoration.suffixIcon].
class NoteFieldActions extends StatelessWidget {
  final TextEditingController controller;

  const NoteFieldActions({super.key, required this.controller});

  Future<void> _copy(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    final text = controller.text;
    if (text.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: text));
    messenger.showSnackBar(const SnackBar(content: Text('Note copied')));
  }

  Future<void> _paste(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    final pasted = data?.text;
    if (pasted == null || pasted.isEmpty) {
      messenger.showSnackBar(const SnackBar(
        content: Text(
            'Nothing to paste, or your browser blocked clipboard access.'),
      ));
      return;
    }
    controller.value = applyPaste(controller.value, pasted);
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton(
          key: const Key('note-copy'),
          tooltip: 'Copy note',
          icon: const Icon(Icons.copy_outlined, size: 18),
          visualDensity: VisualDensity.compact,
          onPressed: () => _copy(context),
        ),
        IconButton(
          key: const Key('note-paste'),
          tooltip: 'Paste into note',
          icon: const Icon(Icons.content_paste_outlined, size: 18),
          visualDensity: VisualDensity.compact,
          onPressed: () => _paste(context),
        ),
      ],
    );
  }
}

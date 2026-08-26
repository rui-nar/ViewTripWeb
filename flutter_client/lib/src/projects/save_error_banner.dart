/// Inline save-failure banner shared by dialog `_save()` flows. A SnackBar
/// would render behind the modal barrier while a dialog is open and never be
/// seen (segment_dialog.dart's issue #20), so failed saves show this
/// errorContainer-colored banner inline instead. This is the fourth copy of
/// this exact widget block (after memory_dialog.dart, journal_dialog.dart,
/// encounter_dialog.dart) so person_form_dialog.dart/group_form_dialog.dart
/// share this instead of copying it a fifth/sixth time.
library;

import 'package:flutter/material.dart';

class SaveErrorBanner extends StatelessWidget {
  final String message;
  const SaveErrorBanner({super.key, required this.message});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: theme.colorScheme.errorContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(Icons.error_outline,
              size: 18, color: theme.colorScheme.onErrorContainer),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.onErrorContainer),
            ),
          ),
        ],
      ),
    );
  }
}

/// Reusable editor for a list of social links — a network dropdown + handle per
/// row, added via a "+" (issues #49, #50). Shared by the person and group modals.
///
/// Uncontrolled: read the current links from the [SocialLinksFieldState.value]
/// getter (via a GlobalKey) at save time.
library;

import 'package:flutter/material.dart';

/// Social networks offered in the "+" picker. Stored lower-case; the value is a
/// free handle or profile URL. Extensible — add a code here and a label below.
const List<String> kSocialNetworks = [
  'instagram',
  'facebook',
  'polarsteps',
  'strava',
  'tiktok',
  'x',
  'linkedin',
  'website',
];

String socialNetworkLabel(String code) => switch (code) {
      'x' => 'X',
      'tiktok' => 'TikTok',
      'linkedin' => 'LinkedIn',
      _ => code.isEmpty ? code : code[0].toUpperCase() + code.substring(1),
    };

/// One editable social-link row: a network selection plus its handle controller.
class _SocialRow {
  String network;
  final TextEditingController handle;
  _SocialRow(this.network, String value)
      : handle = TextEditingController(text: value);
}

class SocialLinksField extends StatefulWidget {
  /// Initial links as `[{network, handle}]` (accepts dynamic-valued maps).
  final List<Map<String, dynamic>> initial;
  const SocialLinksField({super.key, this.initial = const []});

  @override
  State<SocialLinksField> createState() => SocialLinksFieldState();
}

class SocialLinksFieldState extends State<SocialLinksField> {
  late final List<_SocialRow> _rows = [
    for (final e in widget.initial)
      if (e['network'] != null)
        _SocialRow('${e['network']}', '${e['handle'] ?? ''}'),
  ];

  /// The current non-empty links, as `[{network, handle}]`.
  List<Map<String, String>> get value => [
        for (final r in _rows)
          if (r.handle.text.trim().isNotEmpty)
            {'network': r.network, 'handle': r.handle.text.trim()},
      ];

  @override
  void dispose() {
    for (final r in _rows) {
      r.handle.dispose();
    }
    super.dispose();
  }

  void _add() {
    final used = _rows.map((r) => r.network).toSet();
    final next = kSocialNetworks.firstWhere((n) => !used.contains(n),
        orElse: () => kSocialNetworks.first);
    setState(() => _rows.add(_SocialRow(next, '')));
  }

  void _remove(int i) => setState(() => _rows.removeAt(i).handle.dispose());

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text('Social networks', style: theme.textTheme.labelLarge),
            const Spacer(),
            TextButton.icon(
              key: const Key('add-social'),
              onPressed: _add,
              icon: const Icon(Icons.add, size: 18),
              label: const Text('Add'),
            ),
          ],
        ),
        for (var i = 0; i < _rows.length; i++)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(
              children: [
                DropdownButton<String>(
                  value: _rows[i].network,
                  underline: const SizedBox.shrink(),
                  items: [
                    for (final n in kSocialNetworks)
                      DropdownMenuItem(
                          value: n, child: Text(socialNetworkLabel(n))),
                  ],
                  onChanged: (v) =>
                      setState(() => _rows[i].network = v ?? _rows[i].network),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextField(
                    controller: _rows[i].handle,
                    decoration: const InputDecoration(
                      hintText: 'handle or URL',
                      isDense: true,
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                IconButton(
                  key: Key('remove-social-$i'),
                  icon: const Icon(Icons.close, size: 18),
                  onPressed: () => _remove(i),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

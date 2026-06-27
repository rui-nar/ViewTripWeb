import 'package:flutter/material.dart';

/// One entry in the [AddSpeedDial] fan: an icon, a label pill, and what to do.
class SpeedDialAction {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  const SpeedDialAction({
    required this.icon,
    required this.label,
    required this.onTap,
  });
}

/// An expanding "+" floating action button. Tapping the main button fans the
/// [actions] upward (each a small FAB + label); tapping the main button again,
/// or picking an action, collapses it. Owner-only screens host this; viewers
/// never see it.
class AddSpeedDial extends StatefulWidget {
  final List<SpeedDialAction> actions;
  final String tooltip;
  const AddSpeedDial({super.key, required this.actions, this.tooltip = 'Add'});

  @override
  State<AddSpeedDial> createState() => _AddSpeedDialState();
}

class _AddSpeedDialState extends State<AddSpeedDial>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 220),
  );
  bool _open = false;

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  void _toggle() {
    setState(() => _open = !_open);
    _open ? _ctrl.forward() : _ctrl.reverse();
  }

  void _select(SpeedDialAction action) {
    _toggle(); // collapse first
    action.onTap();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        // Fanned actions — present only while (partially) open, so they're
        // neither visible nor tappable when collapsed.
        AnimatedBuilder(
          animation: _ctrl,
          builder: (context, _) {
            if (_ctrl.value == 0) return const SizedBox.shrink();
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                for (final action in widget.actions) _buildAction(action),
              ],
            );
          },
        ),
        FloatingActionButton(
          heroTag: 'add_speed_dial_main',
          tooltip: widget.tooltip,
          onPressed: _toggle,
          child: AnimatedBuilder(
            animation: _ctrl,
            builder: (_, child) => Transform.rotate(
              angle: _ctrl.value * 0.7853981633974483, // up to 45°
              child: child,
            ),
            child: const Icon(Icons.add),
          ),
        ),
      ],
    );
  }

  Widget _buildAction(SpeedDialAction action) {
    final cs = Theme.of(context).colorScheme;
    final curved = CurvedAnimation(parent: _ctrl, curve: Curves.easeOut);
    return FadeTransition(
      opacity: curved,
      child: ScaleTransition(
        scale: curved,
        alignment: Alignment.centerRight,
        child: Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Material(
                color: cs.surface,
                elevation: 3,
                borderRadius: BorderRadius.circular(8),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                  child: Text(
                    action.label,
                    style: TextStyle(color: cs.onSurface, fontSize: 13.5),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              FloatingActionButton.small(
                heroTag: 'add_speed_dial_${action.label}',
                onPressed: () => _select(action),
                child: Icon(action.icon),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

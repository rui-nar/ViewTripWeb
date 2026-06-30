/// Approve other devices that are waiting to read your encrypted data (#26,
/// Phase 5). Shown on an already-trusted device; approving re-wraps the CMK to
/// the pending device's public key so it can unlock without any password.
library;

import 'package:flutter/material.dart';

import '../core/design_tokens.dart';
import 'encryption_service.dart';

class ManageDevicesScreen extends StatefulWidget {
  final EncryptionService service;
  const ManageDevicesScreen({super.key, required this.service});

  @override
  State<ManageDevicesScreen> createState() => _ManageDevicesScreenState();
}

class _ManageDevicesScreenState extends State<ManageDevicesScreen> {
  List<PendingDevice>? _pending;
  String? _error;
  final _approving = <String>{};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final pending = await widget.service.pendingDevices();
      if (mounted) setState(() => _pending = pending);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _approve(PendingDevice device) async {
    setState(() => _approving.add(device.publicKeyB64));
    try {
      await widget.service.approveDevice(device.publicKeyB64);
      if (!mounted) return;
      setState(() {
        _pending = _pending!
            .where((d) => d.publicKeyB64 != device.publicKeyB64)
            .toList();
        _approving.remove(device.publicKeyB64);
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Device approved')),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() => _approving.remove(device.publicKeyB64));
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Couldn\'t approve device: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Devices')),
      body: SafeArea(child: _body(context)),
    );
  }

  Widget _body(BuildContext context) {
    if (_error != null) {
      return Center(child: Text(_error!));
    }
    final pending = _pending;
    if (pending == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (pending.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'No devices are waiting for approval.\nSign in on another device to '
            'add it here.',
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.all(16),
      itemCount: pending.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (context, i) {
        final d = pending[i];
        final busy = _approving.contains(d.publicKeyB64);
        return ListTile(
          leading: const Icon(Icons.devices_other),
          title: Text(d.label.isEmpty ? 'New device' : d.label),
          subtitle: Text(
            'key ${d.publicKeyB64.substring(0, d.publicKeyB64.length.clamp(0, 10))}…',
            style: monoStyle(fontSize: 12),
          ),
          trailing: busy
              ? const SizedBox(
                  width: 18, height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2))
              : FilledButton(
                  onPressed: () => _approve(d),
                  child: const Text('Approve'),
                ),
        );
      },
    );
  }
}

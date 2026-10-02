import 'package:flutter/material.dart';

import '../services/api.dart';
import '../services/backend_config.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final ctl = TextEditingController();
  bool busy = true;
  String status = '';

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    ctl.text = await BackendConfig.baseUrl();
    if (mounted) setState(() => busy = false);
  }

  Future<void> _save() async {
    setState(() => busy = true);
    final previous = await BackendConfig.baseUrl();
    try {
      await BackendConfig.save(ctl.text);
      final resolved = await BackendConfig.baseUrl();
      ctl.text = resolved;
      final h = await PhilthyApi().health();
      status = 'Connected to $resolved • ${h['service']} v${h['version']}';
    } catch (e) {
      try {
        await BackendConfig.save(previous);
        ctl.text = previous;
      } catch (_) {}
      status = 'Backend validation failed. The previous verified URL was kept. $e';
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _reset() async {
    await BackendConfig.reset();
    await _load();
    if (mounted) setState(() => status = 'Reset to verified build default.');
  }

  @override
  Widget build(BuildContext c) => Scaffold(
    appBar: AppBar(title: const Text('Backend settings')),
    body: ListView(padding: const EdgeInsets.all(16), children: [
      const Text('Enter the API base URL only. PhilthySports automatically removes /health, /ready, /docs, /openapi.json, or /v1 suffixes so endpoint paths are not accidentally doubled.'),
      const SizedBox(height: 16),
      TextField(controller: ctl, keyboardType: TextInputType.url, autocorrect: false, decoration: const InputDecoration(labelText: 'Python API base URL', hintText: 'https://api.example.com', border: OutlineInputBorder())),
      const SizedBox(height: 12),
      FilledButton.icon(onPressed: busy ? null : _save, icon: const Icon(Icons.save), label: const Text('Save and test connection')),
      TextButton(onPressed: busy ? null : _reset, child: const Text('Reset to verified build default')),
      if (busy) const LinearProgressIndicator(),
      if (status.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 12), child: Text(status)),
    ]),
  );
}

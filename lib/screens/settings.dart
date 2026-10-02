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

  @override
  void dispose() { ctl.dispose(); super.dispose(); }

  Future<void> _load() async {
    final base = await BackendConfig.baseUrl();
    if (!mounted) return;
    ctl.text = base;
    setState(() => busy = false);
  }

  Future<void> _save() async {
    setState(() => busy = true);
    try {
      final resolved = BackendConfig.validate(ctl.text);
      final h = await PhilthyApi(baseUrl: resolved).health();
      await BackendConfig.save(resolved);
      if (!mounted) return;
      ctl.text = resolved;
      status = 'Connected to $resolved • ${h['service']} v${h['version']}';
    } catch (e) {
      status = 'Connection could not be verified after bounded retries. Your saved backend URL was kept. $e';
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
      const Text('Enter the API base URL only. PhilthyParleys automatically removes /health, /ready, /docs, /openapi.json, or /v1 suffixes so endpoint paths are not accidentally doubled.'),
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

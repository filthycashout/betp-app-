import 'dart:convert';

import 'package:flutter/material.dart';

import '../services/api.dart';

class SystemStatusScreen extends StatefulWidget {
  const SystemStatusScreen({super.key});

  @override
  State<SystemStatusScreen> createState() => _SystemStatusScreenState();
}

class _SystemStatusScreenState extends State<SystemStatusScreen> {
  final api = PhilthyApi();
  bool busy = true;
  String? error;
  Map<String, dynamic> health = const {};
  Map<String, dynamic> system = const {};
  Map<String, dynamic> models = const {};
  Map<String, dynamic> registry = const {};
  Map<String, dynamic> props = const {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final results = await Future.wait([
        api.health(),
        api.systemStatus(),
        api.modelStatus(),
        api.modelRegistry(),
        api.propCapabilities(),
      ]);
      if (!mounted) return;
      setState(() {
        health = results[0];
        system = results[1];
        models = results[2];
        registry = results[3];
        props = results[4];
      });
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  dynamic _redact(dynamic value) {
    if (value is Map) {
      final out = <String, dynamic>{};
      value.forEach((key, val) {
        final k = key.toString();
        final lower = k.toLowerCase();
        if (lower.contains('password') ||
            lower.contains('secret') ||
            lower.contains('token') ||
            lower.contains('authorization') ||
            lower.endsWith('_key') ||
            lower == 'key') {
          out[k] = '<redacted>';
        } else {
          out[k] = _redact(val);
        }
      });
      return out;
    }
    if (value is List) return value.map(_redact).toList();
    return value;
  }

  Widget _card(String title, Map<String, dynamic> data) {
    final text = const JsonEncoder.withIndent('  ').convert(_redact(data));
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            SelectableText(text),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('System & model status')),
        body: RefreshIndicator(
          onRefresh: _load,
          child: ListView(
            padding: const EdgeInsets.all(12),
            children: [
              const Card(
                child: Padding(
                  padding: EdgeInsets.all(12),
                  child: Text(
                    'PhilthyParleys is not limited to a market-only baseline. When no signed '
                    'trained model has passed every v8 gate, the governed hybrid runtime uses '
                    'fresh de-vigged market evidence when available and chronological completed-game '
                    'form when a usable market probability is absent. A trained model becomes active '
                    'only after chronology, OOF calibration, leakage, metric, schema, checksum, signature, '
                    'sample-sufficiency and mobile-parity checks pass.',
                  ),
                ),
              ),
              if (busy) const LinearProgressIndicator(),
              if (error != null)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Text(error!, style: const TextStyle(color: Colors.red)),
                  ),
                ),
              if (!busy && error == null) ...[
                _card('Backend health', health),
                _card('Production gates', system),
                _card('Model governance', models),
                _card('Candidate & promoted model registry', registry),
                _card('Player prop capabilities', props),
              ],
            ],
          ),
        ),
      );
}

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
  final Map<String, String> sectionErrors = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (!mounted) return;
    setState(() {
      busy = true;
      error = null;
      sectionErrors.clear();
    });

    Future<void> loadSection(
      String key,
      Future<Map<String, dynamic>> Function() loader,
      void Function(Map<String, dynamic>) assign,
    ) async {
      try {
        final value = await loader();
        if (!mounted) return;
        setState(() {
          assign(value);
          sectionErrors.remove(key);
        });
      } catch (e) {
        if (!mounted) return;
        setState(() {
          sectionErrors[key] = '$e';
        });
      }
    }

    await Future.wait([
      loadSection('Backend health', api.health, (value) => health = value),
      loadSection('Production gates', api.systemStatus, (value) => system = value),
      loadSection('Model governance', api.modelStatus, (value) => models = value),
      loadSection(
        'Candidate & promoted model registry',
        api.modelRegistry,
        (value) => registry = value,
      ),
      loadSection(
        'Player prop capabilities',
        api.propCapabilities,
        (value) => props = value,
      ),
    ]);

    if (!mounted) return;
    setState(() {
      busy = false;
      if (sectionErrors.length == 5) {
        error =
            'All status endpoints are unavailable. Pull to retry or verify the backend URL.';
      }
    });
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

  Widget _sectionError(String title, String message) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 6),
            Text(
              'Unavailable: $message',
              style: const TextStyle(color: Colors.redAccent),
            ),
          ],
        ),
      ),
    );
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
              if (health.isNotEmpty) _card('Backend health', health),
              if (sectionErrors['Backend health'] != null)
                _sectionError(
                  'Backend health',
                  sectionErrors['Backend health']!,
                ),
              if (system.isNotEmpty) _card('Production gates', system),
              if (sectionErrors['Production gates'] != null)
                _sectionError(
                  'Production gates',
                  sectionErrors['Production gates']!,
                ),
              if (models.isNotEmpty) _card('Model governance', models),
              if (sectionErrors['Model governance'] != null)
                _sectionError(
                  'Model governance',
                  sectionErrors['Model governance']!,
                ),
              if (registry.isNotEmpty)
                _card('Candidate & promoted model registry', registry),
              if (sectionErrors['Candidate & promoted model registry'] != null)
                _sectionError(
                  'Candidate & promoted model registry',
                  sectionErrors['Candidate & promoted model registry']!,
                ),
              if (props.isNotEmpty) _card('Player prop capabilities', props),
              if (sectionErrors['Player prop capabilities'] != null)
                _sectionError(
                  'Player prop capabilities',
                  sectionErrors['Player prop capabilities']!,
                ),
            ],
          ),
        ),
      );
}

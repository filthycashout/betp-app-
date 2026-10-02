import 'package:flutter/material.dart';

import '../models/game.dart';
import '../services/api.dart';

class GameDetailScreen extends StatefulWidget {
  final GameSummary game;
  const GameDetailScreen({super.key, required this.game});

  @override
  State<GameDetailScreen> createState() => _GameDetailScreenState();
}

class _GameDetailScreenState extends State<GameDetailScreen> {
  final api = PhilthyApi();
  Map<String, dynamic>? detail;
  Map<String, dynamic>? props;
  Map<String, dynamic>? parlays;
  String? err;
  bool busy = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      busy = true;
      err = null;
    });
    try {
      final d = await api.detail(widget.game);
      Map<String, dynamic> p = {'props': [], 'configured_markets': []};
      Map<String, dynamic> pa = {'parlays': []};
      try {
        p = await api.props(widget.game);
      } catch (_) {}
      try {
        pa = await api.parlays(widget.game);
      } catch (_) {}
      if (mounted) {
        setState(() {
          detail = d;
          props = p;
          parlays = pa;
        });
      }
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String _friendlyMarket(dynamic raw) => raw
      .toString()
      .replaceAll('player_', '')
      .replaceAll('batter_', 'batter ')
      .replaceAll('pitcher_', 'pitcher ')
      .replaceAll('_', ' ');

  @override
  Widget build(BuildContext c) {
    final d = detail ?? {};
    final score = Map<String, dynamic>.from(d['score_prediction'] ?? {});
    final reasons = List<dynamic>.from(score['reasons'] ?? []);
    final pl = List<dynamic>.from(props?['props'] ?? []);
    final configured = List<dynamic>.from(props?['configured_markets'] ?? []);
    final propStatus = props?['status']?.toString();
    final propMessage = props?['message']?.toString();
    final parl = List<dynamic>.from(parlays?['parlays'] ?? []);

    return Scaffold(
      appBar: AppBar(title: Text('${widget.game.away} @ ${widget.game.home}')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (busy) const LinearProgressIndicator(),
            if (err != null)
              Text(err!, style: const TextStyle(color: Colors.red)),
            Text('ML & final score', style: Theme.of(c).textTheme.headlineSmall),
            Text('Pick: ${score['pick'] ?? 'Unavailable'}'),
            Text(
              'Projected: ${score['away'] ?? '—'} - ${score['home'] ?? '—'}',
            ),
            ...reasons.map(
              (r) => ListTile(
                leading: const Icon(Icons.insights),
                title: Text('$r'),
              ),
            ),
            const Divider(),
            Text('Player props', style: Theme.of(c).textTheme.headlineSmall),
            if (pl.isEmpty)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        propMessage ??
                            'No fresh player-prop lines are available for this game yet.',
                      ),
                      if (propStatus != null) ...[
                        const SizedBox(height: 6),
                        Text('Status: $propStatus'),
                      ],
                      if (configured.isNotEmpty) ...[
                        const SizedBox(height: 10),
                        const Text('Supported markets:'),
                        const SizedBox(height: 6),
                        Wrap(
                          spacing: 6,
                          runSpacing: 6,
                          children: configured
                              .map((m) => Chip(label: Text(_friendlyMarket(m))))
                              .toList(),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ...pl.map(
              (p) => ListTile(
                title: Text(
                  '${p['player']} ${p['recommended_side'] ?? ''} '
                  '${p['line'] ?? ''} ${_friendlyMarket(p['market'])}',
                ),
                subtitle: Text('${p['reason'] ?? ''}'),
              ),
            ),
            const Divider(),
            Text(
              'Best four 3-leg parlays',
              style: Theme.of(c).textTheme.headlineSmall,
            ),
            if (parl.isEmpty)
              const Text(
                'Fewer than three eligible live legs are available; no parlay is fabricated.',
              ),
            ...parl.asMap().entries.map(
              (e) => Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Parlay ${e.key + 1}'),
                      ...List<dynamic>.from(e.value['legs'] ?? [])
                          .map((x) => Text('• ${x['label']}')),
                      Text(
                        'Dependency: ${e.value['dependency_method'] ?? 'unscored'}',
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

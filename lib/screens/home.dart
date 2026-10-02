import 'package:flutter/material.dart';

import '../models/game.dart';
import '../services/api.dart';
import '../widgets/game_card.dart';
import 'game_detail.dart';
import 'settings.dart';
import 'system_status.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final api = PhilthyApi();
  final ctl = TextEditingController();
  List<GameSummary> games = [];
  bool busy = true;
  String? err;

  @override
  void initState() {
    super.initState();
    _loadToday();
  }

  Future<void> _loadToday() async {
    setState(() {
      busy = true;
      err = null;
    });
    try {
      final x = await api.today();
      if (mounted) setState(() => games = x);
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _search() async {
    final q = ctl.text.trim();
    if (q.isEmpty) return _loadToday();
    setState(() {
      busy = true;
      err = null;
    });
    try {
      final x = await api.search(q);
      if (mounted) setState(() => games = x);
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _openMultisportParlay(int legs) async {
    setState(() {
      busy = true;
      err = null;
    });
    try {
      final payload = await api.multisportParlay(legs);
      if (!mounted) return;
      final selected = List<dynamic>.from(payload['legs'] ?? []);
      final reasons = List<dynamic>.from(payload['reasoning'] ?? []);
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        builder: (sheetContext) => SafeArea(
          child: FractionallySizedBox(
            heightFactor: 0.88,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(
                  '$legs-leg multisport parlay',
                  style: Theme.of(sheetContext).textTheme.headlineSmall,
                ),
                const SizedBox(height: 8),
                Text(
                  'Status: ${payload['status'] ?? 'UNKNOWN'} • '
                  'Legs: ${payload['actual_legs'] ?? selected.length}/${payload['requested_legs'] ?? legs} • '
                  'Sports: ${List<dynamic>.from(payload['sports_included'] ?? []).join(', ')}',
                ),
                const SizedBox(height: 6),
                Text(
                  'Profile: ${payload['selection_profile'] ?? '—'} • '
                  'Props: ${payload['player_prop_legs'] ?? 0} • '
                  'Market picks: ${payload['market_pick_legs'] ?? 0}',
                ),
                const SizedBox(height: 12),
                for (final leg in selected)
                  Card(
                    child: ListTile(
                      title: Text(
                        '${leg['sport']} • ${leg['type'] ?? 'pick'} • ${leg['label']}',
                      ),
                      subtitle: Text(
                        [
                          '${leg['matchup'] ?? ''}'
                              '${leg['event_time_pacific'] != null ? ' • ${leg['event_time_pacific']} PT' : ''}',
                          if (leg['type'] == 'player_prop')
                            [
                              if (leg['player'] != null) 'Player: ${leg['player']}',
                              if (leg['market'] != null) 'Market: ${leg['market']}',
                              if (leg['side'] != null) 'Side: ${leg['side']}',
                              if (leg['line'] != null) 'Line: ${leg['line']}',
                            ].join(' • '),
                          'Probability: ${leg['probability'] != null ? ((leg['probability'] as num) * 100).toStringAsFixed(1) : '—'}%',
                          if (leg['best_available_book'] != null ||
                              leg['best_available_price'] != null)
                            'Best fresh quote: ${leg['best_available_book'] ?? 'book unavailable'} '
                            '${leg['best_available_price'] ?? ''}',
                          if (leg['as_of'] != null) 'Quote as-of: ${leg['as_of']}',
                          if (List<dynamic>.from(
                            leg['contributing_books'] ?? const [],
                          ).isNotEmpty)
                            'Contributing books: ${List<dynamic>.from(leg['contributing_books']).join(', ')}',
                          '${leg['reason'] ?? ''}',
                        ].where((x) => x.trim().isNotEmpty).join('\n'),
                      ),
                    ),
                  ),
                if (selected.length < legs)
                  const Card(
                    child: Padding(
                      padding: EdgeInsets.all(12),
                      child: Text(
                        'The backend did not fabricate missing legs. A fresh eligible '
                        'probability or mapped player-prop market is required for every leg.',
                      ),
                    ),
                  ),
                const Divider(),
                Text(
                  'Why these legs',
                  style: Theme.of(sheetContext).textTheme.titleLarge,
                ),
                for (final reason in reasons)
                  ListTile(
                    leading: const Icon(Icons.insights_outlined),
                    title: Text('$reason'),
                  ),
                const SizedBox(height: 8),
                Text(
                  'Dependency: ${payload['dependency_method'] ?? 'unscored'}',
                ),
              ],
            ),
          ),
        ),
      );
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext c) {
    final groups = <String, List<GameSummary>>{};
    for (final g in games) {
      groups.putIfAbsent(g.sport, () => []).add(g);
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('PhilthyParleys'),
        actions: [
          IconButton(
            tooltip: 'System & model status',
            icon: const Icon(Icons.verified_user_outlined),
            onPressed: () => Navigator.push(
              c,
              MaterialPageRoute(builder: (_) => const SystemStatusScreen()),
            ),
          ),
          IconButton(
            tooltip: 'Backend settings',
            icon: const Icon(Icons.settings),
            onPressed: () => Navigator.push(
              c,
              MaterialPageRoute(builder: (_) => const SettingsScreen()),
            ).then((_) => _loadToday()),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _loadToday,
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            TextField(
              controller: ctl,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _search(),
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                hintText: 'Search team, matchup, date, or sport',
                suffixIcon: IconButton(
                  icon: const Icon(Icons.arrow_forward),
                  onPressed: _search,
                ),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Multisport parlays',
                      style: Theme.of(c).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      'Each 7, 10, and 14-leg card is built independently from the best fresh multisport picks. '
                      'Player props are deliberately included when mapped live prop markets pass the credential gate.',
                    ),
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final legs in const [7, 10, 14])
                          FilledButton.tonal(
                            onPressed: busy ? null : () => _openMultisportParlay(legs),
                            child: Text('$legs-leg best picks + props'),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 8),
            if (busy) const LinearProgressIndicator(),
            if (err != null)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(err!, style: const TextStyle(color: Colors.red)),
                      const SizedBox(height: 8),
                      const Text(
                        'If this is a backend connection error, open the gear icon '
                        'and set the Python API URL.',
                      ),
                    ],
                  ),
                ),
              ),
            for (final sport in const ['NFL', 'NBA', 'MLB', 'NHL']) ...[
              Padding(
                padding: const EdgeInsets.only(top: 12, bottom: 6),
                child: Text(
                  "$sport today's games",
                  style: Theme.of(c).textTheme.headlineSmall,
                ),
              ),
              if ((groups[sport] ?? []).isEmpty)
                const Text('No matching scheduled games.'),
              for (final g in groups[sport] ?? [])
                GameCard(
                  game: g,
                  onTap: () => Navigator.push(
                    c,
                    MaterialPageRoute(
                      builder: (_) => GameDetailScreen(game: g),
                    ),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

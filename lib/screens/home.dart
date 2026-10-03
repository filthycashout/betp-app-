import 'package:flutter/material.dart';

import '../models/game.dart';
import '../services/api.dart';
import '../widgets/game_card.dart';
import 'game_detail.dart';
import 'settings.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final api = PhilthyApi();
  final ctl = TextEditingController();
  List<GameSummary> games = [];
  Map<String, List<GameSummary>> nextGamesBySport = {};
  bool busy = true;
  String? err;
  String _selectedSport = 'NFL';
  int _tabIndex = 0;

  static const _accent = Color(0xFF78D8C3);
  static const _selectedSurface = Color(0xFF355149);

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
      final feed = await api.todayFeed();
      if (mounted) {
        setState(() {
          games = feed.games;
          nextGamesBySport = feed.nextGamesBySport;
        });
      }
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
      if (mounted) {
        setState(() {
          games = x;
          nextGamesBySport = {};
        });
      }
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


  IconData _sportIcon(String sport) {
    switch (sport) {
      case 'NFL':
        return Icons.sports_football_rounded;
      case 'NBA':
        return Icons.sports_basketball_rounded;
      case 'MLB':
        return Icons.sports_baseball_rounded;
      case 'NHL':
        return Icons.sports_hockey_rounded;
      default:
        return Icons.sports;
    }
  }

  Widget _sportSelector() {
    const sports = ['NFL', 'NBA', 'MLB', 'NHL'];
    return Row(
      children: [
        for (var i = 0; i < sports.length; i++) ...[
          if (i > 0) const SizedBox(width: 8),
          Expanded(
            child: SizedBox(
              height: 62,
              child: OutlinedButton(
                onPressed: () => setState(() => _selectedSport = sports[i]),
                style: OutlinedButton.styleFrom(
                  foregroundColor: _selectedSport == sports[i]
                      ? Colors.white
                      : const Color(0xFFD9DEDB),
                  backgroundColor: _selectedSport == sports[i]
                      ? _selectedSurface
                      : const Color(0xFF101612),
                  side: BorderSide(
                    color: _selectedSport == sports[i]
                        ? _selectedSurface
                        : const Color(0xFF53605A),
                    width: 1.2,
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(18),
                  ),
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                ),
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        _sportIcon(sports[i]),
                        color: _selectedSport == sports[i]
                            ? const Color(0xFFE8F4F0)
                            : _accent,
                        size: 26,
                      ),
                      const SizedBox(width: 7),
                      Text(
                        sports[i],
                        style: const TextStyle(
                          fontWeight: FontWeight.w700,
                          fontSize: 17,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ],
    );
  }

  @override
  Widget build(BuildContext c) {
    final groups = <String, List<GameSummary>>{};
    for (final g in games) {
      groups.putIfAbsent(g.sport, () => []).add(g);
    }

    return Scaffold(
      backgroundColor: const Color(0xFF0B100C),
      appBar: AppBar(
        toolbarHeight: 76,
        backgroundColor: const Color(0xFF07110D),
        surfaceTintColor: Colors.transparent,
        leadingWidth: 72,
        leading: const Padding(
          padding: EdgeInsets.only(left: 18),
          child: Icon(
            Icons.auto_graph_rounded,
            size: 38,
            color: Color(0xFFF0F4F1),
          ),
        ),
        titleSpacing: 4,
        title: const Text(
          'PhilthySports',
          style: TextStyle(
            fontSize: 28,
            fontWeight: FontWeight.w800,
            letterSpacing: -0.5,
          ),
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 18),
            child: Center(
              child: Text(
                _selectedSport,
                style: const TextStyle(
                  fontSize: 19,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1.2,
                ),
              ),
            ),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _loadToday,
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            _sportSelector(),
            const SizedBox(height: 16),
            TextField(
              controller: ctl,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _search(),
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                hintText: 'Search team, matchup, date, or sport',
                filled: true,
                fillColor: const Color(0xFF0E130F),
                contentPadding: const EdgeInsets.symmetric(vertical: 20, horizontal: 16),
                suffixIcon: IconButton(
                  icon: const Icon(Icons.arrow_forward),
                  onPressed: _search,
                ),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            if (_tabIndex == 2)
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
                        'If this is a backend connection error, open Settings '
                        'and verify the Python API URL.',
                      ),
                    ],
                  ),
                ),
              ),
            for (final sport in [_selectedSport]) ...[
              Padding(
                padding: const EdgeInsets.only(top: 12, bottom: 6),
                child: Text(
                  _tabIndex == 1 ? '$sport picks' : "$sport today's games",
                  style: Theme.of(c).textTheme.headlineSmall,
                ),
              ),
              if ((groups[sport] ?? []).isEmpty) ...[
                const Text('No games scheduled for today.'),
                if ((nextGamesBySport[sport] ?? []).isNotEmpty) ...[
                  const SizedBox(height: 6),
                  Text(
                    'Next scheduled',
                    style: Theme.of(c).textTheme.titleMedium,
                  ),
                  for (final g in nextGamesBySport[sport] ?? [])
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
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tabIndex,
        height: 78,
        backgroundColor: const Color(0xFF111713),
        indicatorColor: _selectedSurface,
        surfaceTintColor: Colors.transparent,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        onDestinationSelected: (value) async {
          if (value == 3) {
            await Navigator.push(
              c,
              MaterialPageRoute(builder: (_) => const SettingsScreen()),
            );
            if (mounted) {
              setState(() => _tabIndex = 0);
              _loadToday();
            }
            return;
          }
          setState(() => _tabIndex = value);
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.sports_score_outlined),
            selectedIcon: Icon(Icons.sports_score_rounded),
            label: 'Live',
          ),
          NavigationDestination(
            icon: Icon(Icons.auto_graph_outlined),
            selectedIcon: Icon(Icons.auto_graph_rounded),
            label: 'Picks',
          ),
          NavigationDestination(
            icon: Icon(Icons.format_list_numbered_outlined),
            selectedIcon: Icon(Icons.format_list_numbered_rounded),
            label: 'Parlay',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings_rounded),
            label: 'Settings',
          ),
        ],
      ),
    );
  }
}

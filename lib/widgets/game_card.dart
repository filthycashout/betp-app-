import 'package:flutter/material.dart';
import '../models/game.dart';

class GameCard extends StatelessWidget {
  final GameSummary game;
  final VoidCallback onTap;

  const GameCard({super.key, required this.game, required this.onTap});

  String _pct(dynamic value) {
    if (value is num) return '${(value * 100).toStringAsFixed(1)}%';
    return '—';
  }

  String _line(dynamic value) {
    if (value is! num) return '—';
    final n = value.toDouble();
    final digits = n % 1 == 0 ? 0 : 1;
    final body = n.toStringAsFixed(digits);
    return n > 0 ? '+$body' : body;
  }

  @override
  Widget build(BuildContext c) {
    final m = game.market;
    final s = game.projectedScore;

    final spreadPick = m['spread_pick']?.toString();
    final spreadLine = spreadPick == game.home
        ? m['home_spread']
        : spreadPick == game.away
            ? m['away_spread']
            : null;
    final totalPick = m['total_pick']?.toString();
    final totalLine = m['total'];

    final spreadText = spreadPick == null || spreadLine == null
        ? 'Unavailable'
        : '$spreadPick ${_line(spreadLine)} (${_pct(m['spread_pick_probability'])})';
    final totalText = totalPick == null || totalLine == null
        ? 'Unavailable'
        : '$totalPick $totalLine (${_pct(m['total_pick_probability'])})';

    return Card(
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${game.away} @ ${game.home}',
                style: Theme.of(c).textTheme.titleMedium,
              ),
              const SizedBox(height: 4),
              Text('${game.eventTime} PT'),
              const SizedBox(height: 8),
              Text('ML: ${game.pick ?? 'Unavailable'}'),
              Text('Spread lean: $spreadText'),
              Text('O/U lean: $totalText'),
              Text(
                'Projected score: ${s['away'] ?? '—'} - ${s['home'] ?? '—'}',
              ),
              if (game.propsToWatch.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  'Props: ${game.propsToWatch.take(3).map((p) => '${p['player']} ${p['recommended_side'] ?? ''} ${p['line'] ?? ''}').join(' • ')}',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

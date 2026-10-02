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
    final predictions = game.predictions;
    final ml = Map<String, dynamic>.from(predictions['moneyline'] ?? {});
    final spread = Map<String, dynamic>.from(predictions['spread'] ?? {});
    final total = Map<String, dynamic>.from(predictions['total'] ?? {});

    final spreadPick =
        spread['pick']?.toString() ?? m['spread_pick']?.toString();
    final spreadLine = spread['line'] ??
        (spreadPick == game.home
            ? m['home_spread']
            : spreadPick == game.away
                ? m['away_spread']
                : null);
    final spreadProbability =
        spread['probability'] ?? m['spread_pick_probability'];
    final totalPick = total['pick']?.toString() ?? m['total_pick']?.toString();
    final totalLine = total['line'] ?? m['total'];
    final totalProbability =
        total['probability'] ?? m['total_pick_probability'];

    final spreadText = spreadPick == null
        ? 'Unavailable'
        : spreadLine == null
            ? spreadPick
            : '$spreadPick ${_line(spreadLine)}'
                '${spreadProbability is num ? ' (${_pct(spreadProbability)})' : ''}';
    final totalText = totalPick == null
        ? total['projected_total'] is num
            ? 'Projected ${total['projected_total']}'
            : 'Unavailable'
        : totalLine == null
            ? totalPick
            : '$totalPick $totalLine'
                '${totalProbability is num ? ' (${_pct(totalProbability)})' : ''}';

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
              Text(
                'ML: ${ml['pick'] ?? game.pick ?? 'Unavailable'}'
                '${ml['home_win_probability'] is num ? ' • Home ${_pct(ml['home_win_probability'])}' : ''}',
              ),
              if ((ml['source'] ?? game.probabilitySource) != null)
                Text(
                  'Source: ${(ml['source'] ?? game.probabilitySource).toString().replaceAll('_', ' ')}',
                  style: Theme.of(c).textTheme.bodySmall,
                ),
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

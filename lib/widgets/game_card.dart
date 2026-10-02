import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
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

  String _score(dynamic value) {
    if (value is! num) return '—';
    final n = value.toDouble();
    return n % 1 == 0 ? n.toInt().toString() : n.toStringAsFixed(1);
  }

  String _eventTime(String raw) {
    final cleaned = raw.replaceAll(' PT', '').trim();
    final match = RegExp(
      r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})',
    ).firstMatch(cleaned);
    if (match == null) return raw;
    final wallClock = DateTime(
      int.parse(match.group(1)!),
      int.parse(match.group(2)!),
      int.parse(match.group(3)!),
      int.parse(match.group(4)!),
      int.parse(match.group(5)!),
    );
    final formatted = DateFormat('EEE MMM d • h:mm a')
        .format(wallClock)
        .replaceAll('\u202F', ' ')
        .replaceAll('\u00A0', ' ');
    return '$formatted PT';
  }

  String? _liveSummary(Map<String, dynamic> live) {
    if (live.isEmpty) return null;
    final rawState = (live['state'] ?? live['status'] ?? '').toString();
    final state = rawState.toUpperCase();
    final completed = live['completed'] == true ||
        state == 'FINAL' ||
        state == 'OFF' ||
        state == 'POST';

    if (completed) {
      final hasScore =
          live['away_score'] is num || live['home_score'] is num;
      return hasScore
          ? 'FINAL • ${_score(live['away_score'])} - ${_score(live['home_score'])}'
          : 'FINAL';
    }

    final isLive = state == 'LIVE' ||
        state == 'IN' ||
        state == 'IN_PROGRESS' ||
        state == 'INPROGRESS';
    if (!isLive) {
      if (state == 'PRE' || state == 'SCHEDULED') return 'Pregame';
      return rawState.isEmpty ? null : rawState;
    }

    final parts = <String>['LIVE'];
    if (live['away_score'] is num || live['home_score'] is num) {
      parts.add(
        '${_score(live['away_score'])} - ${_score(live['home_score'])}',
      );
    }
    if (live['period'] != null) parts.add('Period ${live['period']}');
    final clock = live['clock']?.toString().trim();
    if (clock != null && clock.isNotEmpty) parts.add(clock);
    return parts.join(' • ');
  }

  @override
  Widget build(BuildContext c) {
    final m = game.market;
    final s = game.projectedScore;
    final predictions = game.predictions;
    final live = game.live;
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
              Text(_eventTime(game.eventTime)),
              if (_liveSummary(live) != null)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    _liveSummary(live)!,
                    style: Theme.of(c).textTheme.bodyMedium,
                  ),
                ),
              const SizedBox(height: 8),
              Text(
                'ML: ${ml['pick'] ?? game.pick ?? 'Unavailable'}'
                '${ml['home_win_probability'] is num ? ' • Home ${_pct(ml['home_win_probability'])}' : ''}',
              ),
              if ((ml['source'] ?? game.probabilitySource) != null)
                Text(
                  (ml['source'] ?? game.probabilitySource) == 'unavailable'
                      ? 'Source: no verified pregame probability yet'
                      : 'Source: ${(ml['source'] ?? game.probabilitySource).toString().replaceAll('_', ' ')}',
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

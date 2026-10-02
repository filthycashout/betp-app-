import 'package:flutter_test/flutter_test.dart';
import 'package:philthysports/models/game.dart';

void main() {
  test('GameSummary parses the v8 API contract', () {
    final game = GameSummary.fromJson({
      'event_id': 'evt-1',
      'sport': 'NFL',
      'home': 'Home',
      'away': 'Away',
      'event_time': '2026-10-01T17:00:00Z',
      'date': '2026-10-01',
      'odds_event_id': 'odds-1',
      'pick': 'Home',
      'market': {'home_ml': -120, 'away_ml': 105},
      'projected_score': {'home': 24.5, 'away': 21.0},
      'props_to_watch': [
        {'player': 'Example', 'market': 'player_pass_yds'}
      ],
    });
    expect(game.sport, 'NFL');
    expect(game.home, 'Home');
    expect(game.oddsEventId, 'odds-1');
    expect(game.market['home_ml'], -120);
    expect(game.propsToWatch, hasLength(1));
  });
}

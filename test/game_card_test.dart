import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:philthysports/models/game.dart';
import 'package:philthysports/widgets/game_card.dart';

GameSummary _game({
  Map<String, dynamic>? live,
  String eventTime = '2026-10-02T15:30:00-07:00',
}) =>
    GameSummary(
      eventId: 'evt',
      sport: 'NHL',
      home: 'Red Wings',
      away: 'Rangers',
      eventTime: eventTime,
      date: '2026-10-02',
      market: const {},
      projectedScore: const {},
      predictions: const {
        'moneyline': {'source': 'unavailable'},
      },
      live: live ?? const {},
      propsToWatch: const [],
    );

void main() {
  testWidgets('game card formats Pacific time and integer live scores',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: GameCard(
            game: _game(
              live: const {
                'state': 'LIVE',
                'status': 'LIVE',
                'away_score': 0.0,
                'home_score': 0.0,
                'period': 1,
              },
            ),
            onTap: () {},
          ),
        ),
      ),
    );

    expect(find.text('Fri Oct 2 • 3:30 PM PT'), findsOneWidget);
    expect(find.text('LIVE • 0 - 0 • Period 1'), findsOneWidget);
    expect(find.textContaining('0.0 - 0.0'), findsNothing);
    expect(
      find.text('Source: no verified pregame probability yet'),
      findsOneWidget,
    );
  });

  testWidgets('pregame card does not display a fake period', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: GameCard(
            game: _game(
              live: const {
                'state': 'PRE',
                'status': 'PRE',
                'period': 1,
              },
            ),
            onTap: () {},
          ),
        ),
      ),
    );

    expect(find.text('Pregame'), findsOneWidget);
    expect(find.textContaining('Period 1'), findsNothing);
  });
}

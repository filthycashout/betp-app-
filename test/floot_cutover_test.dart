import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:philthysports/models/game.dart';
import 'package:philthysports/services/api.dart';
import 'package:philthysports/services/backend_config.dart';
import 'package:philthysports/services/mobile_network.dart';

void main() {
  const goodHealth =
      '{"json":{"status":"ok","service":"philthysports-runtime","product":"PhilthyParleys","host":"Floot"}}';

  test('Floot base rewrites API paths and unwraps SuperJSON', () async {
    final paths = <String>[];
    final api = PhilthyApi(
      baseUrl: 'https://philthyparleys.floot.app',
      delay: (_) async {},
      client: MockClient((request) async {
        paths.add(request.url.path);
        if (request.url.path == '/_api/health') {
          return http.Response(goodHealth, 200);
        }
        if (request.url.path == '/_api/v1/system/status') {
          return http.Response('{"json":{"ok":true}}', 200);
        }
        return http.Response('{"error":"missing"}', 404);
      }),
    );

    expect((await api.health())['status'], 'ok');
    expect((await api.systemStatus())['ok'], isTrue);
    expect(paths, containsAllInOrder([
      '/_api/health',
      '/_api/v1/system/status',
    ]));
  });

  test('Floot dynamic game route becomes fixed query endpoint', () async {
    Uri? seen;
    final game = GameSummary.fromJson({
      'event_id': '259b5df9aa0d10257f56de78523495e0',
      'odds_event_id': '259b5df9aa0d10257f56de78523495e0',
      'sport': 'NFL',
      'home': 'Dallas Cowboys',
      'away': 'Tampa Bay Buccaneers',
      'event_time': '2026-10-09T00:15:00Z',
      'event_time_pacific': '2026-10-08T17:15 PT',
      'date': '2026-10-08',
      'market': {},
      'projected_score': {},
      'predictions': {},
      'live': {},
      'props_to_watch': [],
    });
    final api = PhilthyApi(
      baseUrl: 'https://philthyparleys.floot.app',
      delay: (_) async {},
      client: MockClient((request) async {
        seen = request.url;
        return http.Response(
          '{"json":{"prediction_status":"MARKET_BASELINE_FALLBACK"}}',
          200,
        );
      }),
    );

    final detail = await api.detail(game);
    expect(detail['prediction_status'], 'MARKET_BASELINE_FALLBACK');
    expect(seen!.path, '/_api/v1/game');
    expect(seen!.queryParameters['sport'], 'NFL');
    expect(seen!.queryParameters['event_id'], game.eventId);
    expect(seen!.queryParameters['date'], game.date);
  });

  test('retired Render defaults always migrate to Floot', () async {
    SharedPreferences.setMockInitialValues({
      'philthy_backend_url': 'https://philthysports-api-v9.onrender.com',
    });
    expect(
      await BackendConfig.baseUrl(),
      'https://philthyparleys.floot.app',
    );

    await expectLater(
      BackendConfig.save('https://philthysports-api-v9.onrender.com'),
      throwsA(isA<FormatException>()),
    );
  });

  test('mobile bridge accepts only approved Floot read routes', () {
    for (final url in [
      'https://philthyparleys.floot.app/_api/health',
      'https://philthyparleys.floot.app/_api/v1/search?sport=NFL',
      'https://philthyparleys.floot.app/_api/v1/game?sport=NFL&event_id=259b5df9aa0d10257f56de78523495e0',
      'https://philthyparleys.floot.app/_api/v1/game/props?sport=NBA&event_id=85a2379bc49135f2759709e55af0c4c6',
      'https://philthyparleys.floot.app/_api/v1/evidence/verify?signal=1c906c17-705a-8741-f4ec-68ae021b11fa',
    ]) {
      expect(MobileNetwork.isAllowed(Uri.parse(url)), isTrue, reason: url);
    }

    for (final url in [
      'https://philthyparleys.floot.app/_api/v1/ci/android-signing-material',
      'https://philthyparleys.floot.app/_api/v1/evidence/verify?signal=bad',
      'https://philthyparleys.floot.app/_api/v1/game?sport=NFL&event_id=../../admin',
      'https://philthysports-api-v9.onrender.com/v1/search?sport=NFL',
    ]) {
      expect(MobileNetwork.isAllowed(Uri.parse(url)), isFalse, reason: url);
    }
  });
}

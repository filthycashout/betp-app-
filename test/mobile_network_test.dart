import 'package:flutter_test/flutter_test.dart';
import 'package:philthysports/services/mobile_network.dart';

void main() {
  test('mobile bridge permits only the required read-only sports feeds', () {
    for (final url in [
      'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=20261004',
      'https://statsapi.mlb.com/api/v1/schedule?sportId=1',
      'https://api-web.nhle.com/v1/score/2026-10-03',
      'https://philthyparleys.floot.app/_api/v1/game/props?sport=NFL&event_id=401872965&date=2026-10-04',
      'https://philthyparleys.floot.app/_api/v1/game/best9?sport=NFL&event_id=401872965&date=2026-10-04',
      'https://philthyparleys.floot.app/_api/v1/picks/best12?date=2026-10-06',
      'https://philthyparleys.floot.app/_api/v1/parlays/best3?date=2026-10-06',
      'https://philthyparleys.floot.app/_api/v1/evidence/signals?sport=NFL&date=2026-10-06&limit=250',
      'https://philthyparleys.floot.app/_api/v1/evidence/verify?signal=bbafef42-6149-5690-910d-f458d9a00f6c',
    ]) {
      expect(MobileNetwork.isAllowed(Uri.parse(url)), isTrue, reason: url);
    }

    for (final url in [
      'http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',
      'https://site.api.espn.com.attacker.test/apis/site/v2/sports/football/nfl/scoreboard',
      'https://user:pass@statsapi.mlb.com/api/v1/schedule',
      'https://philthyparleys.floot.app/_api/v1/ci/android-signing-material',
      'https://philthyparleys.floot.app/_api/v1/evidence/delete',
      'https://philthyparleys.floot.app/_api/v1/evidence/verify?signal=not-a-signal',
      'https://philthyparleys.floot.app/_api/v1/game?sport=NFL&event_id=../../admin',
      'https://philthysports-api-v9.onrender.com/v1/search?sport=NFL',
      'file:///data/local/tmp/secret',
    ]) {
      expect(MobileNetwork.isAllowed(Uri.parse(url)), isFalse, reason: url);
    }

    expect(
      MobileNetwork.isAllowed(
        Uri.parse('https://statsapi.mlb.com/api/v1/schedule').replace(port: 8443),
      ),
      isFalse,
    );
  });

  test('backend deadline stays bounded for Floot and public feeds', () {
    expect(
      MobileNetwork.timeoutFor(Uri.parse('https://philthyparleys.floot.app/_api/health')),
      const Duration(seconds: 45),
    );
    expect(
      MobileNetwork.timeoutFor(Uri.parse('https://statsapi.mlb.com/api/v1/schedule')),
      const Duration(seconds: 45),
    );
  });
}

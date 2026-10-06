import 'package:flutter_test/flutter_test.dart';
import 'package:philthysports/services/mobile_network.dart';
void main() {
  test('mobile bridge permits only the required read-only sports feeds', () {
    for (final url in [
      'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=20261004',
      'https://statsapi.mlb.com/api/v1/schedule?sportId=1',
      'https://api-web.nhle.com/v1/score/2026-10-03',
      'https://philthysports-api-v9.onrender.com/v1/games/NFL/401872965/props?date=2026-10-04',
      'https://philthysports-api-v9.onrender.com/v1/games/NFL/401872965/best9?date=2026-10-04',
      'https://philthysports-api-v9.onrender.com/v1/picks/best12?date=2026-10-06',
      'https://philthysports-api-v9.onrender.com/v1/parlays/best3?date=2026-10-06',
      'https://philthysports-api-v9.onrender.com/v1/evidence/signals?sport=NFL&date=2026-10-06&limit=250',
      'https://philthysports-api-v9.onrender.com/v1/evidence/verify/bbafef42-6149-5690-910d-f458d9a00f6c',
    ]) {expect(MobileNetwork.isAllowed(Uri.parse(url)),isTrue);}
    for (final url in [
      'http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',
      'https://site.api.espn.com.attacker.test/apis/site/v2/sports/football/nfl/scoreboard',
      'https://user:pass@statsapi.mlb.com/api/v1/schedule',
      'https://philthysports-api-v9.onrender.com/v1/ci/android-signing-material',
      'https://philthysports-api-v9.onrender.com/v1/evidence/delete',
      'https://philthysports-api-v9.onrender.com/v1/evidence/verify/not-a-signal',
      'https://philthysports-api-v9.onrender.com/v1/games/NFL/401872965/admin',
      'file:///data/local/tmp/secret',
    ]) {expect(MobileNetwork.isAllowed(Uri.parse(url)),isFalse);}
    expect(MobileNetwork.isAllowed(Uri.parse('https://statsapi.mlb.com/api/v1/schedule').replace(port:8443)),isFalse);
  });
  test('backend deadline permits cold starts and stays bounded', () {
    expect(MobileNetwork.timeoutFor(Uri.parse('https://philthysports-api-v9.onrender.com/health')), const Duration(seconds:95));
    expect(MobileNetwork.timeoutFor(Uri.parse('https://statsapi.mlb.com/api/v1/schedule')), const Duration(seconds:45));
  });
}

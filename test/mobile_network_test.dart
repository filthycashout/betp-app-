import 'package:flutter_test/flutter_test.dart';
import 'package:philthysports/services/mobile_network.dart';
void main() {
  test('mobile bridge permits only the required read-only sports feeds', () {
    for (final url in [
      'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=20261004',
      'https://statsapi.mlb.com/api/v1/schedule?sportId=1',
      'https://api-web.nhle.com/v1/score/2026-10-03',
      'https://philthysports-powerhouse-v8.onrender.com/v1/games/NFL/401872965/props?date=2026-10-04',
    ]) {expect(MobileNetwork.isAllowed(Uri.parse(url)),isTrue);}
    for (final url in [
      'http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',
      'https://site.api.espn.com.attacker.test/apis/site/v2/sports/football/nfl/scoreboard',
      'https://user:pass@statsapi.mlb.com/api/v1/schedule',
      'https://statsapi.mlb.com:8443/api/v1/schedule',
      'https://philthysports-powerhouse-v8.onrender.com/v1/ci/android-signing-material',
      'file:///data/local/tmp/secret',
    ]) {expect(MobileNetwork.isAllowed(Uri.parse(url)),isFalse);}
  });
}

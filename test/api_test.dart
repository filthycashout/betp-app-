import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:philthysports/services/api.dart';
import 'package:philthysports/services/backend_config.dart';

void main() {
  const good = '{"status":"ok","service":"philthysports-runtime","version":"1.5.0"}';
  test('health recovers from transient 502 and 503', () async {
    var calls = 0;
    final api = PhilthyApi(baseUrl: 'https://example.com', delay: (_) async {},
      client: MockClient((request) async {
        expect(request.url.path, '/health');
        calls++;
        return http.Response(calls < 3 ? 'gateway' : good, calls == 1 ? 502 : calls == 2 ? 503 : 200);
      }));
    expect((await api.health())['status'], 'ok');
    expect(calls, 3);
  });
  test('health retries stop after five failed attempts', () async {
    var calls = 0;
    final api = PhilthyApi(baseUrl: 'https://example.com', delay: (_) async {},
      client: MockClient((_) async {calls++; return http.Response('gateway', 502);}));
    await expectLater(api.health(), throwsException);
    expect(calls, 5);
  });
  test('wrong service is rejected and candidate does not change saved URL', () async {
    SharedPreferences.setMockInitialValues({});
    await BackendConfig.save('https://verified.example.com');
    final api = PhilthyApi(baseUrl: 'https://candidate.example.com',
      client: MockClient((_) async => http.Response('{"status":"ok","service":"other"}', 200)));
    await expectLater(api.health(), throwsFormatException);
    expect(await BackendConfig.baseUrl(), 'https://verified.example.com');
  });
  test('permanent failure is not retried', () async {
    var calls=0;
    final api=PhilthyApi(baseUrl:'https://example.com', delay: (_) async {},
      client:MockClient((_) async {calls++;return http.Response('',401);}));
    await expectLater(api.health(),throwsException);
    expect(calls,1);
  });
  test('backend URL must be HTTPS and contain no credentials', () {
    expect(() => BackendConfig.validate('http://example.com'),throwsFormatException);
    expect(() => BackendConfig.validate('https://user:password@example.com'),throwsFormatException);
  });
}

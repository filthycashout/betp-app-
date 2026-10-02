import 'package:flutter_test/flutter_test.dart';
import 'package:philthysports/services/backend_config.dart';

void main() {
  test('normalizes endpoint URLs to a base URL', () {
    expect(BackendConfig.normalize('https://example.com/health'), 'https://example.com');
    expect(BackendConfig.normalize('https://example.com/v1/health'), 'https://example.com');
    expect(BackendConfig.normalize('https://example.com/api/v1/health?x=1'), 'https://example.com');
    expect(BackendConfig.normalize('https://example.com/api/v1'), 'https://example.com');
    expect(BackendConfig.normalize('https://example.com/api'), 'https://example.com');
    expect(BackendConfig.normalize('https://example.com/docs'), 'https://example.com');
    expect(BackendConfig.normalize('https://example.com/'), 'https://example.com');
  });
}

import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:philthysports/main.dart';
import 'package:philthysports/services/api.dart';
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('bundled mobile dashboard and backend health', (tester) async {
    await tester.pumpWidget(const PhilthySportsApp());
    await tester.pump();
    expect(find.byType(WebViewWidget), findsOneWidget);
    final health = await tester.runAsync(() => PhilthyApi().health());
    expect(health?['status'], 'ok');
    expect(health?['service'], 'philthysports-runtime');
    // DOM interactions and score feeds are checked on the exact signed APK by
    // ci/device_smoke.py rather than Flutter finders across a platform view.
  });
}

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:philthysports/main.dart';
import 'package:philthysports/services/api.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('PhilthyParleys device smoke', (tester) async {
    await tester.pumpWidget(const PhilthyParleysApp());
    await tester.pump();

    expect(find.text('PhilthyParleys'), findsOneWidget);
    expect(find.byType(TextField), findsOneWidget);
    expect(find.text('Multisport parlays'), findsOneWidget);
    expect(find.text('7-leg best picks + props'), findsOneWidget);
    expect(find.text('10-leg best picks + props'), findsOneWidget);
    expect(find.text('14-leg best picks + props'), findsOneWidget);

    final healthResult = await tester.runAsync(() => PhilthyApi().health());
    expect(healthResult, isNotNull);
    final health = healthResult!;
    expect(health['status'], 'ok');
    expect(health['service'], 'philthysports-runtime');

    final modelResult = await tester.runAsync(() => PhilthyApi().modelStatus());
    expect(modelResult, isNotNull);
    final models = modelResult!;
    expect(models.keys.toSet(), {'NFL', 'NBA', 'MLB', 'NHL'});

    final propsResult =
        await tester.runAsync(() => PhilthyApi().propCapabilities());
    expect(propsResult, isNotNull);
    final props = propsResult!;
    final sports = Map<String, dynamic>.from(props['sports'] as Map);
    expect(sports.keys.toSet(), {'NFL', 'NBA', 'MLB', 'NHL'});
    expect(
      List<String>.from((sports['MLB'] as Map)['markets'] as List),
      contains('pitcher_outs'),
    );
    expect(
      List<String>.from((sports['MLB'] as Map)['alternate_markets'] as List),
      contains('pitcher_outs_alternate'),
    );
  });
}

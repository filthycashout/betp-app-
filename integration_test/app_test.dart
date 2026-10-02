import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:philthysports/main.dart';
import 'package:philthysports/services/api.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('PhilthySports physical-device smoke', (tester) async {
    await tester.pumpWidget(const PhilthySportsApp());
    await tester.pump();

    expect(find.text('PhilthySports'), findsOneWidget);
    expect(
      find.widgetWithText(TextField, 'Search team, matchup, date, or sport'),
      findsOneWidget,
    );
    expect(find.text('Multisport parlays'), findsOneWidget);
    expect(find.text('7-leg best picks + props'), findsOneWidget);
    expect(find.text('10-leg best picks + props'), findsOneWidget);
    expect(find.text('14-leg best picks + props'), findsOneWidget);

    final health = await tester.runAsync(() => PhilthyApi().health());
    expect(health, isNotNull);
    expect(health!['status'], 'ok');
    expect(health['service'], 'philthysports-runtime');

    final models = await tester.runAsync(() => PhilthyApi().modelStatus());
    expect(models, isNotNull);
    expect(models!.keys.toSet(), {'NFL', 'NBA', 'MLB', 'NHL'});

    final props = await tester.runAsync(() => PhilthyApi().propCapabilities());
    expect(props, isNotNull);
    final sports = Map<String, dynamic>.from(props!['sports'] as Map);
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

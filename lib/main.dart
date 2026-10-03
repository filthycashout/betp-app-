import 'package:flutter/material.dart';

import 'screens/home.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const PhilthySportsApp());
}

class PhilthySportsApp extends StatelessWidget {
  const PhilthySportsApp({super.key});

  @override
  Widget build(BuildContext context) {
    const accent = Color(0xFF78D8C3);
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'PhilthySports',
      theme: ThemeData(
        brightness: Brightness.dark,
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFF0B100C),
        colorScheme: ColorScheme.fromSeed(
          seedColor: accent,
          brightness: Brightness.dark,
          surface: const Color(0xFF101612),
        ),
        cardTheme: CardThemeData(
          color: const Color(0xFF101612),
          surfaceTintColor: Colors.transparent,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
            side: const BorderSide(color: Color(0xFF28342E)),
          ),
        ),
        navigationBarTheme: const NavigationBarThemeData(
          backgroundColor: Color(0xFF111713),
          indicatorColor: Color(0xFF355149),
          labelTextStyle: WidgetStatePropertyAll(
            TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
          ),
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            backgroundColor: accent,
            foregroundColor: const Color(0xFF06110D),
          ),
        ),
      ),
      home: const HomeScreen(),
    );
  }
}

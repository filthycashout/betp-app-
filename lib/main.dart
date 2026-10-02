import 'package:flutter/material.dart';import 'screens/home.dart';
void main(){WidgetsFlutterBinding.ensureInitialized();runApp(const PhilthySportsApp());}
class PhilthySportsApp extends StatelessWidget{const PhilthySportsApp({super.key});@override Widget build(BuildContext c)=>MaterialApp(debugShowCheckedModeBanner:false,title:'PhilthySports',theme:ThemeData(colorScheme:ColorScheme.fromSeed(seedColor:Colors.green,brightness:Brightness.dark),useMaterial3:true),home:const HomeScreen());}

import 'package:flutter/material.dart';import 'screens/home.dart';
void main(){WidgetsFlutterBinding.ensureInitialized();runApp(const PhilthyParleysApp());}
class PhilthyParleysApp extends StatelessWidget{const PhilthyParleysApp({super.key});@override Widget build(BuildContext c)=>MaterialApp(debugShowCheckedModeBanner:false,title:'PhilthyParleys',theme:ThemeData(colorScheme:ColorScheme.fromSeed(seedColor:Colors.green,brightness:Brightness.dark),useMaterial3:true),home:const HomeScreen());}

import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:webview_flutter/webview_flutter.dart';
import '../services/mobile_network.dart';

class MobileDashboard extends StatefulWidget {
  const MobileDashboard({super.key});
  @override
  State<MobileDashboard> createState() => _MobileDashboardState();
}
class _MobileDashboardState extends State<MobileDashboard> {
  late final WebViewController _controller;
  bool _ready = false;
  String? _error;
  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setBackgroundColor(const Color(0xFF0C100F))
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..addJavaScriptChannel('PhilthyNetwork',onMessageReceived:(message) async {
        final response = await MobileNetwork.request(message.message);
        if (mounted) await _controller.runJavaScript('window.__philthyReply(${jsonEncode(response)});');
      })
      ..addJavaScriptChannel('PhilthyLifecycle',onMessageReceived:(message) {
        if (RegExp(r'^SCORES:(NFL|NBA|MLB|NHL):\d+$').hasMatch(message.message)) {
          debugPrint('PHILTHY_${message.message}');
        }
        if (message.message == 'READY' && mounted) {
          debugPrint('PHILTHY_DASHBOARD_READY');
          setState(() {_ready=true;_error=null;});
        }
      })
      ..setNavigationDelegate(NavigationDelegate(
        onNavigationRequest:(request) => request.url.startsWith('file:///android_asset/flutter_assets/assets/dashboard/')
          ? NavigationDecision.navigate : NavigationDecision.prevent,
        onWebResourceError:(error) {
          if (error.isForMainFrame == true && mounted) setState(()=>_error='The dashboard could not open. Tap Retry.');
        },
      ))
      ..loadFlutterAsset('assets/dashboard/index.html');
  }
  Future<void> _back() async {
    final handled = await _controller.runJavaScriptReturningResult("(function(){if(document.querySelector('[data-slot=sheet-content]')){document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return true;}return false;})()");
    if (handled != true && handled != 'true') await SystemNavigator.pop();
  }
  @override
  Widget build(BuildContext context) => PopScope(
    canPop:false,
    onPopInvokedWithResult:(didPop,result) {if(!didPop) _back();},
    child:Scaffold(backgroundColor:const Color(0xFF0C100F),body:SafeArea(child:Stack(children:[
      WebViewWidget(controller:_controller),
      if(!_ready || _error!=null) Positioned.fill(child:ColoredBox(color:const Color(0xFF0C100F),child:Center(child:Column(mainAxisSize:MainAxisSize.min,children:[
        const Icon(Icons.bolt,color:Color(0xFF83E5CA),size:42),
        const SizedBox(height:16),
        const Text('PhilthySports',style:TextStyle(fontSize:26,fontWeight:FontWeight.w700)),
        const SizedBox(height:20),
        if(_error==null) const CircularProgressIndicator(color:Color(0xFF83E5CA)) else ...[
          Text(_error!),
          TextButton(onPressed:(){setState(()=>_error=null);_controller.loadFlutterAsset('assets/dashboard/index.html');},child:const Text('Retry')),
        ],
      ])))),
    ]))),
  );
}

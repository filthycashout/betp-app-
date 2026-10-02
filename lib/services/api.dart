import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/game.dart';
import 'backend_config.dart';

class PhilthyApi {
  Future<Map<String,dynamic>> _get(String path) async {
    final base=await BackendConfig.baseUrl();
    final r=await http.get(Uri.parse('$base$path'),headers:{'Accept':'application/json'}).timeout(const Duration(seconds:20));
    if(r.statusCode<200||r.statusCode>=300){throw Exception('API ${r.statusCode}: ${r.body}');}
    return Map<String,dynamic>.from(jsonDecode(r.body));
  }
  Future<Map<String,dynamic>> health()=>_get('/health');
  Future<List<GameSummary>> today() async {
    final j=await _get('/v1/today?include_props=true&props_limit=3');
    return (j['games'] as List? ?? []).map((x)=>GameSummary.fromJson(Map<String,dynamic>.from(x))).toList();
  }
  Future<List<GameSummary>> search(String q,{String? sport,String? date}) async {
    final params={'q':q,'include_props':'true','props_limit':'3',if(sport!=null&&sport.isNotEmpty)'sport':sport,if(date!=null&&date.isNotEmpty)'date':date};
    final uri=Uri(path:'/v1/search',queryParameters:params); final j=await _get(uri.toString());
    return (j['games'] as List? ?? []).map((x)=>GameSummary.fromJson(Map<String,dynamic>.from(x))).toList();
  }
  Future<Map<String,dynamic>> detail(GameSummary g)=>_get('/v1/games/${g.sport}/${g.eventId}?date=${Uri.encodeQueryComponent(g.date)}');
  Future<Map<String,dynamic>> props(GameSummary g)=>_get('/v1/games/${g.sport}/${g.eventId}/props?odds_event_id=${Uri.encodeQueryComponent(g.oddsEventId??'')}');
  Future<Map<String,dynamic>> parlays(GameSummary g)=>_get('/v1/games/${g.sport}/${g.eventId}/parlays?date=${Uri.encodeQueryComponent(g.date)}');
}

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/game.dart';
import 'backend_config.dart';

class PhilthyApi {
  Future<Map<String, dynamic>> _get(String path) async {
    final base = await BackendConfig.baseUrl();
    final uri = Uri.parse('$base$path');
    final r = await http
        .get(uri, headers: {'Accept': 'application/json'})
        .timeout(const Duration(seconds: 20));

    if (r.statusCode < 200 || r.statusCode >= 300) {
      throw Exception('API ${r.statusCode} for ${uri.path}');
    }

    final decoded = jsonDecode(r.body);
    if (decoded is! Map) {
      throw const FormatException('Backend returned a non-object JSON response.');
    }
    return Map<String, dynamic>.from(decoded);
  }

  Future<Map<String, dynamic>> health() => _get('/health');
  Future<Map<String, dynamic>> systemStatus() => _get('/v1/system/status');
  Future<Map<String, dynamic>> modelStatus() => _get('/v1/models/status');
  Future<Map<String, dynamic>> propCapabilities() => _get('/v1/system/props');

  Future<List<GameSummary>> today() async {
    final j = await _get('/v1/today?include_props=true&props_limit=3');
    return (j['games'] as List? ?? [])
        .map((x) => GameSummary.fromJson(Map<String, dynamic>.from(x)))
        .toList();
  }

  Future<List<GameSummary>> search(
    String q, {
    String? sport,
    String? date,
  }) async {
    final params = {
      'q': q,
      'include_props': 'true',
      'props_limit': '3',
      if (sport != null && sport.isNotEmpty) 'sport': sport,
      if (date != null && date.isNotEmpty) 'date': date,
    };
    final uri = Uri(path: '/v1/search', queryParameters: params);
    final j = await _get(uri.toString());
    return (j['games'] as List? ?? [])
        .map((x) => GameSummary.fromJson(Map<String, dynamic>.from(x)))
        .toList();
  }

  Future<Map<String, dynamic>> detail(GameSummary g) => _get(
        '/v1/games/${g.sport}/${g.eventId}?date=${Uri.encodeQueryComponent(g.date)}',
      );

  Future<Map<String, dynamic>> props(GameSummary g) => _get(
        '/v1/games/${g.sport}/${g.eventId}/props?odds_event_id=${Uri.encodeQueryComponent(g.oddsEventId ?? '')}',
      );

  Future<Map<String, dynamic>> parlays(GameSummary g) => _get(
        '/v1/games/${g.sport}/${g.eventId}/parlays?date=${Uri.encodeQueryComponent(g.date)}',
      );
}

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/game.dart';
import 'backend_config.dart';

class PhilthyApi {
  static const _transientStatuses = {429, 502, 503, 504};

  Future<Map<String, dynamic>> _get(
    String path, {
    int attempts = 2,
    Duration timeout = const Duration(seconds: 20),
    Duration retryBaseDelay = const Duration(milliseconds: 750),
  }) async {
    final base = await BackendConfig.baseUrl();
    final uri = Uri.parse('$base$path');
    Object? lastError;

    for (var attempt = 0; attempt < attempts; attempt++) {
      try {
        final r = await http
            .get(uri, headers: {'Accept': 'application/json'})
            .timeout(timeout);

        if (r.statusCode >= 200 && r.statusCode < 300) {
          final decoded = jsonDecode(r.body);
          if (decoded is! Map) {
            throw const FormatException(
              'Backend returned a non-object JSON response.',
            );
          }
          return Map<String, dynamic>.from(decoded);
        }

        final error = Exception('API ${r.statusCode} for ${uri.path}');
        if (_transientStatuses.contains(r.statusCode) &&
            attempt + 1 < attempts) {
          lastError = error;
          await Future<void>.delayed(retryBaseDelay * (attempt + 1));
          continue;
        }
        throw error;
      } on TimeoutException catch (e) {
        lastError = e;
        if (attempt + 1 >= attempts) rethrow;
        await Future<void>.delayed(retryBaseDelay * (attempt + 1));
      } on http.ClientException catch (e) {
        lastError = e;
        if (attempt + 1 >= attempts) rethrow;
        await Future<void>.delayed(retryBaseDelay * (attempt + 1));
      }
    }

    throw Exception(
      'Backend unavailable after $attempts attempts for ${uri.path}: $lastError',
    );
  }

  Future<Map<String, dynamic>> health() => _get(
        '/health',
        attempts: 5,
        timeout: const Duration(seconds: 25),
        retryBaseDelay: const Duration(seconds: 2),
      );
  Future<Map<String, dynamic>> systemStatus() => _get('/v1/system/status');
  Future<Map<String, dynamic>> modelStatus() => _get('/v1/models/status');
  Future<Map<String, dynamic>> propCapabilities() => _get('/v1/system/props');

  Future<List<GameSummary>> today() async {
    final j = await _get('/v1/today?include_props=true&props_limit=3&days=2');
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

  Future<Map<String, dynamic>> props(
    GameSummary g, {
    List<String>? markets,
  }) {
    final params = {
      'odds_event_id': g.oddsEventId ?? '',
      if (markets != null && markets.isNotEmpty) 'markets': markets.join(','),
    };
    final uri = Uri(
      path: '/v1/games/${g.sport}/${g.eventId}/props',
      queryParameters: params,
    );
    return _get(uri.toString());
  }

  Future<Map<String, dynamic>> parlays(GameSummary g) => _get(
        '/v1/games/${g.sport}/${g.eventId}/parlays?date=${Uri.encodeQueryComponent(g.date)}',
      );

  Future<Map<String, dynamic>> multisportParlay(int legs, {String? date}) {
    final params = {
      'legs': '$legs',
      if (date != null && date.isNotEmpty) 'date': date,
    };
    final uri = Uri(path: '/v1/parlays/multisport', queryParameters: params);
    return _get(uri.toString());
  }
}

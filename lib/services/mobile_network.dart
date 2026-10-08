import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

class MobileNetwork {
  static bool _validSignal(String? value) =>
      value != null &&
      RegExp(r'^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$')
          .hasMatch(value);

  static bool _validEvent(String? value) =>
      value != null &&
      (RegExp(r'^\d{1,20}$').hasMatch(value) ||
          RegExp(r'^[a-fA-F0-9]{32}$').hasMatch(value));

  static bool _flootPathAllowed(Uri uri) {
    const simple = {
      '/_api/health',
      '/_api/v1/system/status',
      '/_api/v1/models/status',
      '/_api/v1/models/registry',
      '/_api/v1/system/props',
      '/_api/v1/live/sources',
      '/_api/v1/data/providers',
      '/_api/v1/data/external-providers',
      '/_api/v1/search',
      '/_api/v1/today',
      '/_api/v1/picks/best12',
      '/_api/v1/parlays/best3',
      '/_api/v1/parlays/multisport',
      '/_api/v1/evidence/signals',
      '/_api/v1/providers/canary',
    };
    if (simple.contains(uri.path)) return true;

    if (uri.path == '/_api/v1/evidence/verify') {
      return _validSignal(uri.queryParameters['signal']);
    }

    if ({
      '/_api/v1/game',
      '/_api/v1/game/props',
      '/_api/v1/game/parlays',
      '/_api/v1/game/best9',
      '/_api/v1/live/game',
    }.contains(uri.path)) {
      final sport = uri.queryParameters['sport'];
      return const {'NFL', 'NBA', 'MLB', 'NHL'}.contains(sport) &&
          _validEvent(uri.queryParameters['event_id']);
    }

    if (uri.path == '/_api/v1/live/scoreboard') {
      return const {'NFL', 'NBA', 'MLB', 'NHL'}
          .contains(uri.queryParameters['sport']);
    }

    return false;
  }

  static bool isAllowed(Uri uri) {
    if (uri.scheme != 'https' ||
        uri.userInfo.isNotEmpty ||
        (uri.hasPort && uri.port != 443) ||
        uri.fragment.isNotEmpty) {
      return false;
    }
    switch (uri.host) {
      case 'site.api.espn.com':
        return RegExp(
          r'^/apis/site/v2/sports/(football/nfl|basketball/nba|baseball/mlb|hockey/nhl)/scoreboard$',
        ).hasMatch(uri.path);
      case 'statsapi.mlb.com':
        return uri.path == '/api/v1/schedule';
      case 'api-web.nhle.com':
        return RegExp(r'^/v1/score/\d{4}-\d{2}-\d{2}$')
            .hasMatch(uri.path);
      case 'philthyparleys.floot.app':
        return _flootPathAllowed(uri);
      case 'philthysports-api-v9.onrender.com':
        return const [
              '/health',
              '/v1/system/status',
              '/v1/models/status',
              '/v1/data/providers',
              '/v1/search',
              '/v1/parlays/multisport',
              '/v1/picks/best12',
              '/v1/parlays/best3',
              '/v1/evidence/signals',
            ].contains(uri.path) ||
            RegExp(
              r'^/v1/games/(NFL|NBA|MLB|NHL)/\d{1,20}(/props|/best9)?$',
            ).hasMatch(uri.path) ||
            RegExp(
              r'^/v1/evidence/verify/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$',
            ).hasMatch(uri.path);
      default:
        return false;
    }
  }

  static Duration timeoutFor(Uri uri) => Duration(
        seconds: uri.host == 'philthysports-api-v9.onrender.com' ? 95 : 45,
      );

  static Future<Map<String, dynamic>> request(String message) async {
    String id = '';
    final client = http.Client();
    try {
      if (message.length > 4096) throw const FormatException();
      final data = jsonDecode(message);
      if (data is! Map || data['id'] is! String || data['url'] is! String) {
        throw const FormatException();
      }
      id = data['id'] as String;
      if (!RegExp(r'^\d{1,12}$').hasMatch(id)) throw const FormatException();
      final uri = Uri.parse(data['url'] as String);
      if (!isAllowed(uri)) {
        return {'id': id, 'error': 'This data address is not allowed.'};
      }
      final request = http.Request('GET', uri)
        ..followRedirects = false
        ..headers['Accept'] = 'application/json';
      return await (() async {
        final response = await client.send(request);
        final bytes = <int>[];
        await for (final chunk in response.stream) {
          bytes.addAll(chunk);
          if (bytes.length > 5000000) throw const FormatException();
        }
        if (uri.host == 'philthysports-api-v9.onrender.com' ||
            uri.host == 'philthyparleys.floot.app') {
          debugPrint('PHILTHY_BACKEND_HTTP:${uri.path}:${response.statusCode}');
        }
        return <String, dynamic>{
          'id': id,
          'status': response.statusCode,
          'body': utf8.decode(bytes),
        };
      })().timeout(timeoutFor(uri));
    } catch (_) {
      return {
        'id': id,
        'error': 'Live data is unavailable. Check your connection and retry.',
        'code': 'NETWORK_UNAVAILABLE',
      };
    } finally {
      client.close();
    }
  }
}

import 'dart:convert';
import 'package:http/http.dart' as http;

class MobileNetwork {
  static bool isAllowed(Uri uri) {
    if (uri.scheme != 'https' || uri.userInfo.isNotEmpty ||
        (uri.hasPort && uri.port != 443) || uri.fragment.isNotEmpty) {
      return false;
    }
    switch (uri.host) {
      case 'site.api.espn.com':
        return RegExp(r'^/apis/site/v2/sports/(football/nfl|basketball/nba|baseball/mlb|hockey/nhl)/scoreboard$').hasMatch(uri.path);
      case 'statsapi.mlb.com':
        return uri.path == '/api/v1/schedule';
      case 'api-web.nhle.com':
        return RegExp(r'^/v1/score/\d{4}-\d{2}-\d{2}$').hasMatch(uri.path);
      case 'philthysports-powerhouse-v8.onrender.com':
        return const ['/health','/v1/system/status','/v1/models/status','/v1/data/providers','/v1/search','/v1/parlays/multisport'].contains(uri.path) ||
            RegExp(r'^/v1/games/(NFL|NBA|MLB|NHL)/\d{1,20}(/props)?$').hasMatch(uri.path);
      default: return false;
    }
  }

  static Future<Map<String, dynamic>> request(String message) async {
    String id = '';
    final client = http.Client();
    try {
      if (message.length > 4096) throw const FormatException();
      final data = jsonDecode(message);
      if (data is! Map || data['id'] is! String || data['url'] is! String) throw const FormatException();
      id = data['id'] as String;
      if (!RegExp(r'^\d{1,12}$').hasMatch(id)) throw const FormatException();
      final uri = Uri.parse(data['url'] as String);
      if (!isAllowed(uri)) return {'id':id,'error':'This data address is not allowed.'};
      final request = http.Request('GET',uri)
        ..followRedirects = false
        ..headers['Accept'] = 'application/json';
      final response = await client.send(request).timeout(const Duration(seconds:45));
      final bytes = <int>[];
      await for (final chunk in response.stream.timeout(const Duration(seconds:45))) {
        bytes.addAll(chunk);
        if (bytes.length > 5000000) throw const FormatException();
      }
      return {'id':id,'status':response.statusCode,'body':utf8.decode(bytes)};
    } catch (_) {
      return {'id':id,'error':'Live data is unavailable. Check your connection and retry.'};
    } finally {client.close();}
  }
}

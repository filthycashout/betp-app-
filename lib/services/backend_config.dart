import 'package:shared_preferences/shared_preferences.dart';

class BackendConfig {
  static const _key = 'philthy_backend_url';
  static const compiledDefault = String.fromEnvironment(
    'PHILTHY_API_BASE_URL',
    defaultValue: 'https://philthysports-powerhouse-v8.onrender.com',
  );

  static const _obsoleteHosts = {
    'philthysports-powerhouse.onrender.com',
  };

  static Future<String> baseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_key)?.trim();
    if (saved == null || saved.isEmpty) return normalize(compiledDefault);

    final normalized = normalize(saved);
    final uri = Uri.tryParse(normalized);
    if (uri != null && _obsoleteHosts.contains(uri.host.toLowerCase())) {
      final migrated = normalize(compiledDefault);
      await prefs.setString(_key, migrated);
      return migrated;
    }
    if (normalized != saved) await prefs.setString(_key, normalized);
    return normalized;
  }

  static Future<void> save(String value) async {
    final normalized = normalize(value);
    final uri = Uri.tryParse(normalized);
    if (uri == null || !uri.hasScheme || !(uri.scheme == 'http' || uri.scheme == 'https') || uri.host.isEmpty) {
      throw const FormatException('Enter a complete http:// or https:// API URL.');
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, normalized);
  }

  static Future<void> reset() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key);
  }

  static String normalize(String value) {
    final raw = value.trim();
    final uri = Uri.tryParse(raw);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      return raw.endsWith('/') ? raw.substring(0, raw.length - 1) : raw;
    }
    var path = uri.path;
    const suffixes = ['/openapi.json', '/docs', '/ready', '/health', '/v1'];
    var changed = true;
    while (changed && path.isNotEmpty && path != '/') {
      changed = false;
      for (final suffix in suffixes) {
        if (path == suffix || path.endsWith(suffix)) {
          path = path.substring(0, path.length - suffix.length);
          if (path.endsWith('/')) path = path.substring(0, path.length - 1);
          changed = true;
          break;
        }
      }
    }
    final cleanUri = Uri(scheme: uri.scheme, host: uri.host, port: uri.hasPort ? uri.port : null, path: path == '/' ? '' : path);
    final normalized = cleanUri.toString();
    return normalized.endsWith('/') ? normalized.substring(0, normalized.length - 1) : normalized;
  }
}

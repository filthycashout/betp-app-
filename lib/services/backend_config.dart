import 'package:shared_preferences/shared_preferences.dart';

class BackendConfig {
  static const _key = 'philthy_backend_url';
  static const compiledDefault = String.fromEnvironment(
    'PHILTHY_API_BASE_URL',
    defaultValue: 'https://philthyparleys.floot.app',
  );

  static const _obsoleteHosts = {
    'philthysports-powerhouse.onrender.com',
    'philthysports-powerhouse-v8.onrender.com',
  };

  // Hosts that have previously been shipped as an automatic production
  // default. A new APK may migrate one of these to its compiledDefault once;
  // an explicit user save marks the current cutover as handled and therefore
  // preserves deliberate rollback/custom-host choices.
  static const _previousDefaultHosts = {
    'philthysports-api-v9.onrender.com',
    'philthyparleys.floot.app',
  };

  static String get _defaultMigrationKey {
    final uri = Uri.tryParse(normalize(compiledDefault));
    final host = (uri?.host.isNotEmpty ?? false)
        ? uri!.host.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), '_')
        : 'custom';
    return 'philthy_backend_default_cutover_$host';
  }

  static Future<String> baseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_key)?.trim();
    if (saved == null || saved.isEmpty) return normalize(compiledDefault);

    final normalized = normalize(saved);
    final uri = Uri.tryParse(normalized);
    final target = normalize(compiledDefault);
    final targetUri = Uri.tryParse(target);

    if (uri != null && _obsoleteHosts.contains(uri.host.toLowerCase())) {
      await prefs.setString(_key, target);
      await prefs.setBool(_defaultMigrationKey, true);
      return target;
    }

    final migrationApplied = prefs.getBool(_defaultMigrationKey) ?? false;
    final isPreviousDefault = uri != null &&
        _previousDefaultHosts.contains(uri.host.toLowerCase());
    final alreadyTarget = uri != null &&
        targetUri != null &&
        uri.host.toLowerCase() == targetUri.host.toLowerCase() &&
        uri.path == targetUri.path;

    if (!migrationApplied && isPreviousDefault && !alreadyTarget) {
      await prefs.setString(_key, target);
      await prefs.setBool(_defaultMigrationKey, true);
      return target;
    }

    if (normalized != saved) await prefs.setString(_key, normalized);
    return normalized;
  }

  static Future<void> save(String value) async {
    final normalized = validate(value);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, normalized);
    // A deliberate manual save wins over automatic provider migration for the
    // runtime compiled into this APK, preserving rollback/custom host choices.
    await prefs.setBool(_defaultMigrationKey, true);
  }

  static String validate(String value) {
    final input = Uri.tryParse(value.trim());
    if (input != null && input.userInfo.isNotEmpty) {
      throw const FormatException('Use a backend URL without credentials.');
    }
    final normalized = normalize(value);
    final uri = Uri.tryParse(normalized);
    if (uri == null || !uri.hasScheme || uri.scheme != 'https' || uri.host.isEmpty) {
      throw const FormatException('Enter a complete HTTPS API URL.');
    }
    return normalized;
  }

  static Future<void> reset() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key);
    await prefs.setBool(_defaultMigrationKey, true);
  }

  static String normalize(String value) {
    final raw = value.trim();
    final uri = Uri.tryParse(raw);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      return raw.endsWith('/') ? raw.substring(0, raw.length - 1) : raw;
    }
    var path = uri.path;
    const suffixes = [
      '/openapi.json',
      '/docs',
      '/ready',
      '/health',
      '/api/v1',
      '/v1',
      '/api',
    ];
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
    final cleanUri = Uri(
      scheme: uri.scheme,
      host: uri.host,
      port: uri.hasPort ? uri.port : null,
      path: path == '/' ? '' : path,
    );
    final normalized = cleanUri.toString();
    return normalized.endsWith('/')
        ? normalized.substring(0, normalized.length - 1)
        : normalized;
  }
}

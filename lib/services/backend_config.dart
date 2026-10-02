import 'package:shared_preferences/shared_preferences.dart';

class BackendConfig {
  static const _key='philthy_backend_url';
  static const compiledDefault=String.fromEnvironment(
    'PHILTHY_API_BASE_URL',
    defaultValue:'http://10.0.2.2:8787',
  );

  static Future<String> baseUrl() async {
    final prefs=await SharedPreferences.getInstance();
    final saved=prefs.getString(_key)?.trim();
    return (saved==null||saved.isEmpty)?compiledDefault:_normalize(saved);
  }

  static Future<void> save(String value) async {
    final uri=Uri.tryParse(value.trim());
    if(uri==null||!uri.hasScheme||!(uri.scheme=='http'||uri.scheme=='https')||uri.host.isEmpty){
      throw const FormatException('Enter a complete http:// or https:// API URL.');
    }
    final prefs=await SharedPreferences.getInstance();
    await prefs.setString(_key,_normalize(value.trim()));
  }

  static Future<void> reset() async {
    final prefs=await SharedPreferences.getInstance();
    await prefs.remove(_key);
  }

  static String _normalize(String value)=>value.endsWith('/')?value.substring(0,value.length-1):value;
}

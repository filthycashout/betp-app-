import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

class ModelBundleManager {
  Future<Map<String,dynamic>> bundledManifest() async => Map<String,dynamic>.from(jsonDecode(await rootBundle.loadString('assets/models/model_manifest.json')));
  Future<File?> updatedBundleFile(String name) async {final d=await getApplicationSupportDirectory(); final f=File('${d.path}/models/$name'); return await f.exists()?f:null;}
  Future<File> installVerifiedUpdate(Uri uri,String fileName,String expectedSha256) async {
    final r=await http.get(uri).timeout(const Duration(seconds:60)); if(r.statusCode!=200) throw Exception('model update HTTP ${r.statusCode}');
    final digest=sha256.convert(r.bodyBytes).toString(); if(digest.toLowerCase()!=expectedSha256.toLowerCase()) throw Exception('model update checksum mismatch');
    final d=Directory('${(await getApplicationSupportDirectory()).path}/models'); await d.create(recursive:true); final f=File('${d.path}/$fileName'); await f.writeAsBytes(r.bodyBytes,flush:true); return f;
  }
}

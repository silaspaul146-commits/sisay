import 'dart:convert';

import 'package:http/http.dart' as http;

import 'config.dart';

class ApiException implements Exception {
  final int status; // 0 = network
  final String code;
  final String message;
  ApiException(this.status, this.code, this.message);
  bool get isNetwork => status == 0;
  bool get isPermanent => status >= 400 && status < 500 && status != 408 && status != 429;
  @override
  String toString() => 'ApiException($status, $code, $message)';
}

class Api {
  final http.Client _http = http.Client();
  static const _timeout = Duration(seconds: 30);

  Future<dynamic> send(String method, String path,
      {Map<String, String>? headers, Object? body, Map<String, String>? query}) async {
    final uri = Uri.parse('$apiBase$path').replace(queryParameters: query);
    final req = http.Request(method, uri);
    req.headers.addAll({'Accept': 'application/json', ...?headers});
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    http.Response res;
    try {
      res = await http.Response.fromStream(await _http.send(req).timeout(_timeout));
    } catch (_) {
      throw ApiException(0, 'network_error', 'No connection to the server.');
    }
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return res.body.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
    }
    Map<String, dynamic>? err;
    try {
      err = (jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>)['error'] as Map<String, dynamic>?;
    } catch (_) {}
    throw ApiException(res.statusCode, err?['code'] as String? ?? 'http_${res.statusCode}',
        err?['message'] as String? ?? 'Request failed (${res.statusCode}).');
  }
}

Api api = Api(); // replaceable in tests

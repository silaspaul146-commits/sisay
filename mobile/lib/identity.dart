import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api.dart';
import 'config.dart';

/// This phone's anonymous identity: an installation id plus a secret token issued by the server
/// (POST /installations). No name, no phone number. The token lives in Android's encrypted storage
/// and is sent only as X-Installation-Token on personal requests (saved places, alerts).
class Identity {
  static const _store = FlutterSecureStorage();
  String? installationId;
  String? token;

  bool get ready => installationId != null && token != null;

  Future<void> load() async {
    installationId = await _store.read(key: 'installation_id');
    token = await _store.read(key: 'installation_token');
  }

  /// Registers once. Safe to call repeatedly (e.g. every time the app opens while offline).
  Future<bool> ensureRegistered() async {
    if (ready) return true;
    try {
      final r = await api.send('POST', '/installations', body: {'platform': 'android', 'app_version': appVersion});
      installationId = r['installation_id'] as String;
      token = r['installation_token'] as String;
      await _store.write(key: 'installation_id', value: installationId);
      await _store.write(key: 'installation_token', value: token);
      return true;
    } on ApiException {
      return false;
    }
  }

  Map<String, String> get headers => {if (token != null) 'X-Installation-Token': token!};
}

final identity = Identity();

import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'identity.dart';

/// Phone notifications through Firebase Cloud Messaging.
///
/// Optional by design: the app builds and runs without a Firebase config (google-services.json).
/// In that case [available] stays false and alerts are only seen inside the app.
///
/// We ask for notification permission in context (right after someone saves a place or route),
/// not on first launch. The server sends "notification" messages on channel `sisay_alerts`, so
/// Android shows them itself while the app is closed; while it is open we show an in-app banner.
class Push extends ChangeNotifier {
  bool available = false;
  bool? allowed; // null = not asked yet
  final navigatorKey = GlobalKey<NavigatorState>();
  final messengerKey = GlobalKey<ScaffoldMessengerState>();

  /// Set by the app shell: opens one alert's detail page.
  void Function(String alertId)? openAlert;
  String? _pendingOpen;

  /// The newest alert that arrived while the app was open (for the in-app banner).
  RemoteMessage? latest;

  /// Ticks each time an alert arrives while the app is open, so lists can refresh.
  final received = ValueNotifier<int>(0);

  Future<void> init() async {
    try {
      await Firebase.initializeApp();
    } catch (_) {
      return; // no Firebase config in this build
    }
    available = true;
    final m = FirebaseMessaging.instance;
    FirebaseMessaging.onMessage.listen((msg) {
      latest = msg;
      received.value++;
      HapticFeedback.heavyImpact();
      notifyListeners();
    });
    FirebaseMessaging.onMessageOpenedApp.listen((msg) => _open(msg.data['alert_id'] as String?));
    // The server sends with HTTP v1 to registration tokens. The newer register()/onRegistered API
    // hands out installation ids for "direct send" instead; move both sides together later.
    // ignore: deprecated_member_use
    m.onTokenRefresh.listen((t) => _register(t, force: true));
    try {
      final first = await m.getInitialMessage();
      _pendingOpen = first?.data['alert_id'] as String?;
    } catch (_) {}
    unawaited(start(prompt: false));
  }

  /// Registers this phone for alerts. With [prompt], asks for permission if not decided yet.
  Future<void> start({required bool prompt}) async {
    if (!available) return;
    final m = FirebaseMessaging.instance;
    try {
      var s = await m.getNotificationSettings();
      if (prompt && s.authorizationStatus == AuthorizationStatus.notDetermined) {
        s = await m.requestPermission();
      }
      final ok =
          s.authorizationStatus == AuthorizationStatus.authorized || s.authorizationStatus == AuthorizationStatus.provisional;
      allowed = s.authorizationStatus == AuthorizationStatus.notDetermined ? null : ok;
      notifyListeners();
      if (!ok) return;
      // ignore: deprecated_member_use
      final token = await m.getToken();
      if (token != null) await _register(token);
    } catch (_) {/* best effort; retried on next launch */}
  }

  Future<void> _register(String token, {bool force = false}) async {
    final prefs = await SharedPreferences.getInstance();
    if (!force && prefs.getString('push_token_sent') == token) return;
    if (!await identity.ensureRegistered()) return;
    try {
      await api.send('POST', '/devices/push-endpoints', headers: identity.headers, body: {'provider': 'fcm', 'token': token});
      await prefs.setString('push_token_sent', token);
    } on ApiException {/* retried next launch */}
  }

  /// Called once the shell is on screen, so a tap on a notification that launched the app lands.
  void shellReady() {
    final id = _pendingOpen;
    _pendingOpen = null;
    if (id != null) _open(id);
  }

  void _open(String? alertId) {
    if (alertId == null) return;
    if (openAlert == null) {
      _pendingOpen = alertId;
    } else {
      openAlert!(alertId);
    }
  }

  void dismissLatest() {
    latest = null;
    notifyListeners();
  }

  void openLatest() {
    final id = latest?.data['alert_id'] as String?;
    dismissLatest();
    _open(id);
  }
}

final push = Push();

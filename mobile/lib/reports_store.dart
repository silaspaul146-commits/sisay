import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:path/path.dart';
import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

import 'api.dart';
import 'identity.dart';

/// Offline-first report queue (Engineering pack 8, UC-08).
///
/// A report is written to SQLite BEFORE any network call, with a stable id that doubles as the
/// Idempotency-Key and a report access token generated on the phone. Sending retries with the
/// same key, so a lost response can never create a duplicate report on the server. States:
/// pending -> sending -> sent, or needs_attention when the server permanently refuses it.
class LocalReport {
  final String id;
  final String category;
  final double lat, lon;
  final int? accuracyM;
  final String source;
  final String? note;
  final DateTime observedAt;
  final DateTime createdAt;
  final String status;
  final String? serverId, reference, error, accessToken;
  final int attempts;

  LocalReport.fromRow(Map<String, Object?> r)
      : id = r['id'] as String,
        category = r['category'] as String,
        lat = r['lat'] as double,
        lon = r['lon'] as double,
        accuracyM = r['accuracy_m'] as int?,
        source = r['source'] as String,
        note = r['note'] as String?,
        observedAt = DateTime.parse(r['observed_at'] as String),
        createdAt = DateTime.parse(r['created_at'] as String),
        status = r['status'] as String,
        serverId = r['server_id'] as String?,
        reference = r['reference'] as String?,
        error = r['error'] as String?,
        accessToken = r['access_token'] as String?,
        attempts = r['attempts'] as int;
}

class ReportsStore extends ChangeNotifier {
  Database? _db;
  bool _syncing = false;
  StreamSubscription? _net;
  Timer? _timer;

  Future<void> open() async {
    _db = await openDatabase(join(await getDatabasesPath(), 'sisay.db'), version: 1, onCreate: (db, _) async {
      await db.execute('''CREATE TABLE reports (
        id TEXT PRIMARY KEY, category TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, accuracy_m INTEGER,
        source TEXT NOT NULL, note TEXT, observed_at TEXT NOT NULL, created_at TEXT NOT NULL,
        status TEXT NOT NULL, access_token TEXT NOT NULL, server_id TEXT, reference TEXT, error TEXT,
        attempts INTEGER NOT NULL DEFAULT 0)''');
    });
    // A crash mid-send leaves 'sending': it is safe to resend with the same key.
    await _db!.update('reports', {'status': 'pending'}, where: "status = 'sending'");
    _net = Connectivity().onConnectivityChanged.listen((r) {
      if (!r.contains(ConnectivityResult.none)) sync();
    });
    _timer = Timer.periodic(const Duration(minutes: 2), (_) => sync());
    unawaited(sync());
  }

  Future<List<LocalReport>> all() async =>
      (await _db!.query('reports', orderBy: 'created_at DESC')).map(LocalReport.fromRow).toList();

  static String _token() {
    final r = Random.secure();
    return 'rpt_${base64Url.encode(List<int>.generate(32, (_) => r.nextInt(256))).replaceAll('=', '')}';
  }

  /// Saves locally first, then tries to send. Returns the local report after the first attempt.
  Future<LocalReport> submit(
      {required String category,
      required double lat,
      required double lon,
      int? accuracyM,
      required String source,
      String? note}) async {
    final id = const Uuid().v4();
    final now = DateTime.now().toUtc().toIso8601String();
    await _db!.insert('reports', {
      'id': id,
      'category': category,
      'lat': lat,
      'lon': lon,
      'accuracy_m': accuracyM,
      'source': source,
      'note': (note == null || note.trim().isEmpty) ? null : note.trim(),
      'observed_at': now,
      'created_at': now,
      'status': 'pending',
      'access_token': _token(),
    });
    notifyListeners();
    await sync();
    return LocalReport.fromRow((await _db!.query('reports', where: 'id = ?', whereArgs: [id])).first);
  }

  Future<void> sync() async {
    if (_db == null || _syncing) return;
    _syncing = true;
    try {
      await identity.ensureRegistered(); // optional for reporting; done opportunistically
      final pending = await _db!.query('reports', where: "status = 'pending'", orderBy: 'created_at');
      for (final row in pending) {
        final r = LocalReport.fromRow(row);
        await _db!.update('reports', {'status': 'sending', 'attempts': r.attempts + 1}, where: 'id = ?', whereArgs: [r.id]);
        notifyListeners();
        try {
          final res = await api.send('POST', '/reports', headers: {
            'Idempotency-Key': r.id,
            'X-Report-Access-Token': r.accessToken!,
            'X-Client-Platform': 'android',
            if (identity.installationId != null) 'X-Installation-ID': identity.installationId!,
          }, body: {
            'category': r.category,
            'location': {'latitude': r.lat, 'longitude': r.lon, 'accuracy_m': r.accuracyM, 'source': r.source},
            if (r.note != null) 'description': r.note,
            'observed_at': r.observedAt.toIso8601String(),
            'client_created_at': r.createdAt.toIso8601String(),
          });
          await _db!.update(
              'reports', {'status': 'sent', 'server_id': res['report_id'], 'reference': res['public_reference'], 'error': null},
              where: 'id = ?', whereArgs: [r.id]);
        } on ApiException catch (e) {
          final permanent = e.isPermanent; // e.g. 422 invalid, 409 key reused: retrying cannot help
          await _db!.update('reports', {'status': permanent ? 'needs_attention' : 'pending', 'error': e.message},
              where: 'id = ?', whereArgs: [r.id]);
          if (e.isNetwork) break; // offline: stop here, try again later
        }
        notifyListeners();
      }
    } finally {
      _syncing = false;
    }
  }

  @override
  void dispose() {
    _net?.cancel();
    _timer?.cancel();
    super.dispose();
  }
}

ReportsStore reportsStore = ReportsStore(); // replaceable in tests

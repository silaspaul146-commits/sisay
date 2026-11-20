// Renders each screen to a PNG for design review, with fake data and a painted map.
// Run: flutter test test/screenshots_test.dart --dart-define=SCREENSHOTS=<output dir>
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sisay/api.dart';
import 'package:sisay/app_state.dart';
import 'package:sisay/config.dart';
import 'package:sisay/identity.dart';
import 'package:sisay/push.dart';
import 'package:sisay/reports_store.dart';
import 'package:sisay/screens/alerts_screen.dart';
import 'package:sisay/screens/incident_screen.dart';
import 'package:sisay/screens/map_screen.dart';
import 'package:sisay/screens/places_screen.dart';
import 'package:sisay/screens/report_screen.dart';
import 'package:sisay/screens/route_editor.dart';
import 'package:sisay/screens/search_screen.dart';
import 'package:sisay/screens/sent_screen.dart';
import 'package:sisay/screens/shell.dart';
import 'package:sisay/screens/welcome.dart';
import 'package:sisay/theme.dart';

const out = String.fromEnvironment('SCREENSHOTS');

String _iso(Duration ago) => DateTime.now().toUtc().subtract(ago).toIso8601String();

Map<String, dynamic> _feature(String id, String cat, double lat, double lon, {String? v, String? life, int mins = 10}) => {
      'type': 'Feature',
      'id': id,
      'geometry': {
        'type': 'Point',
        'coordinates': [lon, lat]
      },
      'properties': {
        'category': cat,
        'verification_status': v ?? 'unverified',
        'lifecycle': life ?? 'active',
        'precision_m': 500,
        'uncertainty_note': null,
        'observed_at': _iso(Duration(minutes: mins)),
        'last_updated_at': _iso(Duration(minutes: mins ~/ 2)),
      },
    };

final _features = [
  _feature('a', 'shooting', defaultLat + .006, defaultLon + .004, mins: 12),
  _feature('b', 'road_blockage', defaultLat - .012, defaultLon - .01, v: 'verified', mins: 50),
  _feature('c', 'fire', defaultLat + .016, defaultLon - .016, life: 'resolved', v: 'verified', mins: 300),
  _feature('d', 'flood', defaultLat - .004, defaultLon + .02, v: 'disputed', mins: 140),
];

final _alerts = [
  {
    'id': 'al1',
    'status': 'active',
    'category': 'shooting',
    'verification_status': 'unverified',
    'acknowledged': false,
    'message': 'Shooting reported nearby. Not confirmed yet.',
    'updated_at': _iso(const Duration(minutes: 4)),
    'issued_at': _iso(const Duration(minutes: 6)),
    'because': {'kind': 'route', 'name': 'Bambili → Bamenda'},
    'uncertainty': 'One person reported this. It may be wrong or already over.',
    'updates': [
      {'message': 'Shooting reported nearby. Not confirmed yet.', 'received_at': _iso(const Duration(minutes: 6))},
      {'message': 'More people reported it. Our team is checking.', 'received_at': _iso(const Duration(minutes: 3))},
    ],
  },
  {
    'id': 'al2',
    'status': 'ended',
    'category': 'fire',
    'verification_status': 'verified',
    'acknowledged': true,
    'message': 'Over: the fire near Home has ended.',
    'updated_at': _iso(const Duration(hours: 5)),
    'issued_at': _iso(const Duration(hours: 7)),
    'because': {'kind': 'place', 'name': 'Home'},
  },
];

class FakeApi extends Api {
  final bool empty;
  FakeApi({this.empty = false});
  @override
  Future<dynamic> send(String method, String path,
      {Map<String, String>? headers, Object? body, Map<String, String>? query}) async {
    if (path == '/public/incidents') return {'features': empty ? [] : _features};
    if (path.startsWith('/public/incidents/')) return _features.firstWhere((f) => path.endsWith('/${f['id']}'));
    if (path == '/alerts') return {'items': empty ? [] : _alerts};
    if (path.startsWith('/alerts/')) return _alerts.first;
    if (path == '/public/place-search') {
      return {
        'items': [
          {'name': 'Nkwen', 'detail': 'Bamenda, Mezam, Northwest', 'latitude': 5.988, 'longitude': 10.184, 'kind': 'neighbourhood'},
          {'name': 'Bambili', 'detail': 'Tubah, Mezam, Northwest', 'latitude': 6.004, 'longitude': 10.257, 'kind': 'town'},
          {'name': 'Commercial Avenue', 'detail': 'Bamenda, Northwest', 'latitude': 5.96, 'longitude': 10.15, 'kind': 'road'},
        ]
      };
    }
    if (path == '/saved-locations') {
      return {
        'items': empty
            ? []
            : [
                {'id': 'p1', 'name': 'Home', 'radius_m': 1000},
                {'id': 'p2', 'name': 'Work · Commercial Avenue', 'radius_m': 500},
                {'id': 'p3', 'name': 'University of Bamenda', 'radius_m': 2000},
              ]
      };
    }
    if (path == '/saved-routes') {
      return {
        'items': empty
            ? []
            : [
                {'id': 'r1', 'name': 'Bambili → Bamenda', 'length_m': 14200, 'corridor_width_m': 1000}
              ]
      };
    }
    if (path == '/alert-subscriptions') {
      return {
        'items': [
          {'id': 's1', 'saved_location_id': 'p1', 'enabled': true},
          {'id': 's2', 'saved_location_id': 'p2', 'enabled': true},
          {'id': 's3', 'saved_location_id': 'p3', 'enabled': false},
          {'id': 's4', 'saved_route_id': 'r1', 'enabled': true},
        ]
      };
    }
    throw ApiException(0, 'network_error', 'offline');
  }
}

LocalReport _local(String status, String cat, Duration ago, {String? ref, String? err}) => LocalReport.fromRow({
      'id': '$status$cat',
      'category': cat,
      'lat': 1.0,
      'lon': 1.0,
      'accuracy_m': 10,
      'source': 'gps',
      'note': null,
      'observed_at': _iso(ago),
      'created_at': _iso(ago),
      'status': status,
      'server_id': null,
      'reference': ref,
      'error': err,
      'access_token': 'x',
      'attempts': 1,
    });

class FakeStore extends ReportsStore {
  @override
  Future<List<LocalReport>> all() async => [
        _local('pending', 'road_blockage', const Duration(minutes: 2)),
        _local('sent', 'shooting', const Duration(minutes: 40), ref: 'SSY-7Q4K'),
        _local('sent', 'flood', const Duration(days: 2), ref: 'SSY-2M9X'),
      ];
  @override
  Future<void> sync() async {}
}

Future<void> _loadFonts() async {
  Future<void> family(String name, List<String> files) async {
    final loader = FontLoader(name);
    for (final f in files) {
      loader.addFont(rootBundle.load(f));
    }
    await loader.load();
  }

  await family('Inter', [
    for (final w in [400, 500, 600, 700]) 'assets/fonts/Inter-$w.ttf'
  ]);
  await family('Manrope', [
    for (final w in [500, 600, 700, 800]) 'assets/fonts/Manrope-$w.ttf'
  ]);
  await family('MaterialIcons', ['fonts/MaterialIcons-Regular.otf']);
}

void main() {
  setUpAll(() async {
    SharedPreferences.setMockInitialValues({});
    await _loadFonts();
    tilesOverride = () => SizedBox.expand(child: CustomPaint(painter: FakeMapPainter()));
    identity.installationId = 'i';
    identity.token = 't';
    reportsStore = FakeStore();
  });

  Future<void> shot(WidgetTester tester, String name, Widget home,
      {String lang = 'en', bool empty = false, Future<void> Function(WidgetTester)? act}) async {
    api = FakeApi(empty: empty);
    await appState.load();
    await appState.setLang(lang);
    tester.view.physicalSize = const Size(1170, 2532);
    tester.view.devicePixelRatio = 3;
    tester.view.padding = const FakeViewPadding(top: 141, bottom: 102);
    tester.view.viewPadding = const FakeViewPadding(top: 141, bottom: 102);
    final key = GlobalKey();
    await tester.pumpWidget(
        RepaintBoundary(key: key, child: MaterialApp(debugShowCheckedModeBanner: false, theme: sisayTheme(), home: home)));
    for (var i = 0; i < 12; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    if (act != null) await act(tester);
    await tester.runAsync(() async {
      final boundary = key.currentContext!.findRenderObject() as RenderRepaintBoundary;
      final image = await boundary.toImage(pixelRatio: 1.5);
      final png = await image.toByteData(format: ui.ImageByteFormat.png);
      await Directory(out).create(recursive: true);
      await File('$out/$name.png').writeAsBytes(png!.buffer.asUint8List());
    });
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(seconds: 1));
  }

  final skip = out.isEmpty;
  testWidgets('01 welcome', (t) => shot(t, '01_welcome', const WelcomeScreen()), skip: skip);
  testWidgets('02 map', (t) => shot(t, '02_map', const Shell()), skip: skip);
  testWidgets('03 map empty', (t) => shot(t, '03_map_empty', const Shell(), empty: true), skip: skip);
  testWidgets('04 report',
      (t) => shot(t, '04_report', const ReportScreen(initialCategory: 'fire', initialPoint: LatLng(defaultLat, defaultLon))),
      skip: skip);
  testWidgets('05 sent', (t) => shot(t, '05_sent', SentScreen(report: _local('sent', 'fire', Duration.zero, ref: 'SSY-7Q4K'))),
      skip: skip);
  testWidgets('06 alerts', (t) => shot(t, '06_alerts', const Shell(initialTab: 1)), skip: skip);
  testWidgets('07 alert detail', (t) => shot(t, '07_alert_detail', const AlertDetailScreen(alertId: 'al1')), skip: skip);
  testWidgets('08 places', (t) => shot(t, '08_places', const Shell(initialTab: 2)), skip: skip);
  testWidgets(
      '09 routes empty',
      (t) => shot(t, '09_routes_empty', const PlacesScreen(), empty: true, act: (t) async {
            await t.tap(find.text('Routes'));
            await t.pump(const Duration(milliseconds: 400));
          }),
      skip: skip);
  testWidgets('10 mine', (t) => shot(t, '10_mine', const Shell(initialTab: 3)), skip: skip);
  testWidgets(
      '11 incident',
      (t) => shot(
          t,
          '11_incident',
          IncidentScreen(
              incident: PublicIncident.fromFeature(_features.first), from: const LatLng(defaultLat - .01, defaultLon))),
      skip: skip);
  testWidgets(
      '12 route editor',
      (t) => shot(t, '12_route_editor', const RouteEditor(), act: (t) async {
            for (final o in [const Offset(90, 520), const Offset(160, 430), const Offset(230, 380), const Offset(300, 250)]) {
              await t.tapAt(o);
              await t.pump(const Duration(milliseconds: 300));
            }
            await t.enterText(find.byType(TextField), 'Bambili → Bamenda');
            for (var i = 0; i < 6; i++) {
              await t.pump(const Duration(milliseconds: 200));
            }
          }),
      skip: skip);
  testWidgets('13 welcome fr', (t) => shot(t, '13_welcome_fr', const WelcomeScreen(), lang: 'fr'), skip: skip);
  testWidgets('14 report empty', (t) => shot(t, '14_report_new', const ReportScreen()), skip: skip);
  testWidgets('15 live alert', (t) async {
    push.latest = const RemoteMessage(
        messageId: 'm1',
        notification: RemoteNotification(
            title: 'Shooting reported on Bambili → Bamenda', body: 'One person reported this. It may be wrong or already over.'),
        data: {'alert_id': 'al1'});
    await shot(t, '15_live_alert', const Shell());
    push.latest = null;
  }, skip: skip);
  testWidgets('16 notifications off', (t) async {
    push.available = true;
    push.allowed = false;
    await shot(t, '16_notif_off', const Shell(initialTab: 2));
    push.available = false;
    push.allowed = null;
  }, skip: skip);
  testWidgets(
      '17 search',
      (t) => shot(t, '17_search', const SearchScreen(), act: (t) async {
            await t.enterText(find.byType(TextField), 'Bam');
            await t.testTextInput.receiveAction(TextInputAction.search);
            for (var i = 0; i < 6; i++) {
              await t.pump(const Duration(milliseconds: 200));
            }
          }),
      skip: skip);
}

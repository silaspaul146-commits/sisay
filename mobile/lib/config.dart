import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// Build-time configuration. Override with --dart-define=API_BASE=... for other environments.
const apiBase = String.fromEnvironment('API_BASE', defaultValue: 'https://sisay.onrender.com/api/v1');

const appPackage = 'org.sisay.app';
const appVersion = '0.2.2';

/// Where the map opens when location is off: Bamenda.
const defaultLat = 5.9631;
const defaultLon = 10.1591;

/// Which map tiles to draw. The server can change this (GET /public/app-config), so a provider
/// that breaks or starts asking for a key can be swapped without a new app release. The last
/// answer is kept on the phone; the built-in default is used until one arrives.
class MapConfig {
  final String tileUrl;
  final String? fallbackUrl;
  final List<String> subdomains;
  final String attribution;
  final int maxNativeZoom;

  /// 1 = provider colours, 0 = grey. Below 1 calms busy basemaps so pins stand out.
  final double saturation;

  const MapConfig({
    required this.tileUrl,
    this.fallbackUrl,
    this.subdomains = const ['a', 'b', 'c'],
    required this.attribution,
    this.maxNativeZoom = 19,
    this.saturation = 0.55,
  });

  /// OpenStreetMap's own tiles, with the Humanitarian (HOT) style as the fallback. Both are free,
  /// keyless and meant for light use with attribution; a pilot at scale needs its own provider.
  static const builtIn = MapConfig(
    tileUrl: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    fallbackUrl: 'https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',
    attribution: '© OpenStreetMap contributors',
  );

  static bool _validUrl(Object? u) =>
      u is String && u.startsWith('https://') && u.contains('{z}') && u.contains('{x}') && u.contains('{y}');

  static MapConfig? fromJson(Object? j) {
    if (j is! Map) return null;
    final url = j['tile_url'];
    if (!_validUrl(url)) return null;
    final fb = j['fallback_url'];
    final subs = j['subdomains'];
    final zoom = j['max_zoom'];
    final sat = j['saturation'];
    return MapConfig(
      tileUrl: url as String,
      fallbackUrl: _validUrl(fb) ? fb as String : null,
      subdomains: subs is List ? subs.whereType<String>().toList() : const ['a', 'b', 'c'],
      attribution: j['attribution'] is String ? j['attribution'] as String : builtIn.attribution,
      maxNativeZoom: zoom is int && zoom >= 10 && zoom <= 22 ? zoom : 19,
      saturation: sat is num ? sat.toDouble().clamp(0.0, 1.0) : 0.55,
    );
  }
}

final mapConfig = ValueNotifier<MapConfig>(MapConfig.builtIn);

/// Uses the saved map settings now, then asks the server for fresh ones in the background.
Future<void> loadMapConfig() async {
  SharedPreferences? prefs;
  try {
    prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString('map_config');
    final c = saved == null ? null : MapConfig.fromJson(jsonDecode(saved));
    if (c != null) mapConfig.value = c;
  } catch (_) {}
  () async {
    try {
      final res = await http.get(Uri.parse('$apiBase/public/app-config')).timeout(const Duration(seconds: 20));
      if (res.statusCode != 200) return;
      final map = (jsonDecode(utf8.decode(res.bodyBytes)) as Map)['map'];
      final c = MapConfig.fromJson(map);
      if (c == null) return;
      mapConfig.value = c;
      await prefs?.setString('map_config', jsonEncode(map));
    } catch (_) {/* keep what we have */}
  }();
}

/// Tests replace the network basemap with a painted one.
Widget Function()? tilesOverride;

ColorFilter _saturation(double s) {
  const r = 0.2126, g = 0.7152, b = 0.0722;
  final i = 1 - s;
  return ColorFilter.matrix(<double>[
    i * r + s, i * g, i * b, 0, 0, //
    i * r, i * g + s, i * b, 0, 0, //
    i * r, i * g, i * b + s, 0, 0, //
    0, 0, 0, 1, 0,
  ]);
}

Widget basemap(BuildContext context) =>
    tilesOverride?.call() ??
    ValueListenableBuilder<MapConfig>(
      valueListenable: mapConfig,
      builder: (context, c, _) => TileLayer(
        key: ValueKey(c.tileUrl),
        urlTemplate: c.tileUrl,
        fallbackUrl: c.fallbackUrl,
        subdomains: c.subdomains,
        userAgentPackageName: appPackage,
        maxNativeZoom: c.maxNativeZoom,
        tileBuilder:
            c.saturation >= 1 ? null : (context, tile, _) => ColorFiltered(colorFilter: _saturation(c.saturation), child: tile),
      ),
    );

import 'package:flutter/widgets.dart';
import 'package:flutter_map/flutter_map.dart';

/// Build-time configuration. Override with --dart-define=API_BASE=... for other environments.
const apiBase = String.fromEnvironment('API_BASE', defaultValue: 'https://sisay.onrender.com/api/v1');

/// Map tiles: CARTO "Voyager", a calm basemap on OpenStreetMap data. Its free tier is for testing
/// only; the pilot needs a tile provider decision (docs/PRODUCT.md, open decisions).
const tileUrl =
    String.fromEnvironment('TILE_URL', defaultValue: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png');
const tileAttribution = '© OpenStreetMap contributors © CARTO';
const appPackage = 'org.sisay.app';
const appVersion = '0.2.1';

/// Where the map opens when location is off: Bamenda.
const defaultLat = 5.9631;
const defaultLon = 10.1591;

/// Tests replace the network basemap with a painted one.
Widget Function()? tilesOverride;

Widget basemap(BuildContext context) =>
    tilesOverride?.call() ??
    TileLayer(
      urlTemplate: tileUrl,
      subdomains: const ['a', 'b', 'c', 'd'],
      retinaMode: RetinaMode.isHighDensity(context),
      userAgentPackageName: appPackage,
      maxNativeZoom: 19,
    );

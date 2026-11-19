import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';

import '../api.dart';
import '../app_state.dart';
import '../config.dart';
import '../identity.dart';
import '../strings.dart';
import '../theme.dart';
import '../widgets.dart';
import 'route_editor.dart';

/// Saved places and routes: each one gets alerts for reports nearby. We store the place or the
/// line you drew, never the phone's movements.
class PlacesScreen extends StatefulWidget {
  const PlacesScreen({super.key});
  @override
  State<PlacesScreen> createState() => _PlacesScreenState();
}

class _PlacesScreenState extends State<PlacesScreen> {
  String _tab = 'places';
  List<Map<String, dynamic>>? _places;
  List<Map<String, dynamic>>? _routes;
  Map<String, Map<String, dynamic>> _subs = {};
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (!await identity.ensureRegistered()) {
      if (mounted) setState(() => _error = tr(appState.lang, 'offline'));
      return;
    }
    try {
      final res = await Future.wait([
        api.send('GET', '/saved-locations', headers: identity.headers),
        api.send('GET', '/saved-routes', headers: identity.headers),
        api.send('GET', '/alert-subscriptions', headers: identity.headers),
      ]);
      if (!mounted) return;
      setState(() {
        _places = (res[0]['items'] as List).cast<Map<String, dynamic>>();
        _routes = (res[1]['items'] as List).cast<Map<String, dynamic>>();
        _subs = {
          for (final x in (res[2]['items'] as List).cast<Map<String, dynamic>>())
            (x['saved_location_id'] ?? x['saved_route_id']) as String: x,
        };
        _error = null;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.isNetwork ? tr(appState.lang, 'offline') : e.message);
    }
  }

  Future<void> _addPlace() async {
    final added = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => const _AddPlaceSheet(),
    );
    if (added == true) _load();
  }

  Future<void> _addRoute() async {
    final added =
        await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const RouteEditor(), fullscreenDialog: true));
    if (added == true) _load();
  }

  Future<void> _toggle(String targetKey, String id, bool on) async {
    final sub = _subs[id];
    HapticFeedback.selectionClick();
    setState(() => _subs = {
          ..._subs,
          id: {...?sub, 'enabled': on}
        });
    try {
      if (sub == null) {
        await api.send('POST', '/alert-subscriptions', headers: identity.headers, body: {targetKey: id});
      } else {
        await api.send('PATCH', '/alert-subscriptions/${sub['id']}', headers: identity.headers, body: {'enabled': on});
      }
      await _load();
    } on ApiException catch (e) {
      _snack(e.message);
      _load();
    }
  }

  Future<void> _delete(String path, String id) async {
    try {
      await api.send('DELETE', '$path/$id', headers: identity.headers);
      await _load();
    } on ApiException catch (e) {
      _snack(e.message);
      _load();
    }
  }

  void _snack(String m) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
  }

  void _settings() => showModalBottomSheet(context: context, builder: (_) => const SettingsSheet());

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final places = _tab == 'places';
    final items = places ? _places : _routes;
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: RefreshIndicator(
          onRefresh: _load,
          child: ListView(padding: const EdgeInsets.only(bottom: 32), children: [
            PageHeader(tr(l, 'places_title'),
                subtitle: tr(l, 'places_sub'),
                action: IconButton(
                    onPressed: _settings, tooltip: tr(l, 'settings'), icon: const Icon(Icons.settings_outlined, color: C.ink2))),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Segmented<String>(
                  options: [('places', tr(l, 'tab_places')), ('routes', tr(l, 'tab_routes'))],
                  value: _tab,
                  onChanged: (v) => setState(() => _tab = v),
                ),
                if (_error != null)
                  Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: T.label.copyWith(color: C.ember))),
                const SizedBox(height: 14),
                if (items == null && _error == null)
                  const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator()))
                else if (items != null && items.isEmpty)
                  EmptyState(
                    icon: places ? Icons.home_outlined : Icons.route_rounded,
                    title: tr(l, places ? 'no_places' : 'no_routes'),
                    body: tr(l, places ? 'no_places_body' : 'no_routes_body'),
                    action: FilledButton.icon(
                      onPressed: places ? _addPlace : _addRoute,
                      icon: const Icon(Icons.add_rounded),
                      label: Text(tr(l, places ? 'add_place' : 'add_route')),
                    ),
                  )
                else if (items != null) ...[
                  SCard(
                    padding: EdgeInsets.zero,
                    child: Column(children: [
                      for (var k = 0; k < items.length; k++) ...[
                        if (k > 0) const Divider(indent: 72),
                        _TargetRow(
                          item: items[k],
                          route: !places,
                          enabled: (_subs[items[k]['id']]?['enabled'] as bool?) ?? false,
                          onToggle: (v) => _toggle(places ? 'saved_location_id' : 'saved_route_id', items[k]['id'] as String, v),
                          onDelete: () => _delete(places ? '/saved-locations' : '/saved-routes', items[k]['id'] as String),
                        ),
                      ],
                    ]),
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: places ? _addPlace : _addRoute,
                    icon: const Icon(Icons.add_rounded),
                    label: Text(tr(l, places ? 'add_place' : 'add_route')),
                  ),
                ],
                const SizedBox(height: 20),
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Icon(Icons.lock_outline_rounded, size: 16, color: C.ink3),
                  const SizedBox(width: 8),
                  Expanded(child: Text(tr(l, 'places_privacy'), style: T.caption)),
                ]),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

class _TargetRow extends StatelessWidget {
  final Map<String, dynamic> item;
  final bool route, enabled;
  final ValueChanged<bool> onToggle;
  final VoidCallback onDelete;
  const _TargetRow(
      {required this.item, required this.route, required this.enabled, required this.onToggle, required this.onDelete});

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final sub = route
        ? '${distance(((item['length_m'] as num?) ?? 0).toDouble())} · ${tr(l, 'alerts_within')} ${distance((item['corridor_width_m'] as num).toDouble() / 2)}'
        : '${tr(l, 'alerts_within')} ${distance((item['radius_m'] as num).toDouble())}';
    return Dismissible(
      key: ValueKey(item['id']),
      direction: DismissDirection.endToStart,
      confirmDismiss: (_) async =>
          await showDialog<bool>(
              context: context,
              builder: (ctx) => AlertDialog(
                    title: Text('${tr(l, 'delete')} "${item['name']}"?', style: T.headline),
                    content: Text(tr(l, 'delete_body'), style: T.body),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr(l, 'cancel'))),
                      TextButton(
                          onPressed: () => Navigator.pop(ctx, true),
                          style: TextButton.styleFrom(foregroundColor: C.ember),
                          child: Text(tr(l, 'delete'))),
                    ],
                  )) ??
          false,
      background: Container(
          alignment: Alignment.centerRight,
          padding: const EdgeInsets.only(right: 20),
          color: C.emberTint,
          child: const Icon(Icons.delete_outline_rounded, color: C.ember)),
      onDismissed: (_) => onDelete(),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
        child: Row(children: [
          IconTile(route ? Icons.route_rounded : _placeIcon(item['name'] as String),
              size: 44, fg: enabled ? C.brand : C.ink3, bg: enabled ? C.brandTint : C.sunk),
          const SizedBox(width: 14),
          Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(item['name'] as String, style: T.bodyStrong.copyWith(fontSize: 16)),
            const SizedBox(height: 2),
            Text(enabled ? sub : tr(l, 'alerts_off'), style: T.caption),
          ])),
          Switch(value: enabled, onChanged: onToggle),
        ]),
      ),
    );
  }

  static IconData _placeIcon(String name) {
    final n = name.toLowerCase();
    if (n.contains('home') || n.contains('maison')) return Icons.home_rounded;
    if (n.contains('work') || n.contains('travail') || n.contains('office') || n.contains('bureau')) return Icons.work_rounded;
    if (n.contains('school') || n.contains('école') || n.contains('ecole') || n.contains('univ')) return Icons.school_rounded;
    if (n.contains('church') || n.contains('église') || n.contains('mosque') || n.contains('mosquée'))
      return Icons.church_rounded;
    if (n.contains('market') || n.contains('marché')) return Icons.storefront_rounded;
    return Icons.place_rounded;
  }
}

/// Add a place: the map shows exactly the circle we'll watch, so "1 km" means something.
class _AddPlaceSheet extends StatefulWidget {
  const _AddPlaceSheet();
  @override
  State<_AddPlaceSheet> createState() => _AddPlaceSheetState();
}

class _AddPlaceSheetState extends State<_AddPlaceSheet> {
  final _map = MapController();
  late final _name = TextEditingController(text: appState.lang == 'fr' ? 'Maison' : 'Home');
  LatLng _point = const LatLng(defaultLat, defaultLon);
  int _radius = 1000;
  bool _located = false, _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _locate();
  }

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _locate() async {
    try {
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
      final p = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 20)));
      if (!mounted) return;
      setState(() {
        _point = LatLng(p.latitude, p.longitude);
        _located = true;
      });
      try {
        _map.move(_point, _zoom);
      } catch (_) {}
    } catch (_) {/* stay on the default; the user can move the map */}
  }

  double get _zoom => switch (_radius) { <= 500 => 14.5, <= 1000 => 13.5, <= 2000 => 12.5, _ => 11.3 };

  Future<void> _save() async {
    final l = appState.lang;
    if (_name.text.trim().isEmpty) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final place = await api.send('POST', '/saved-locations', headers: identity.headers, body: {
        'name': _name.text.trim(),
        'location': {'latitude': _point.latitude, 'longitude': _point.longitude},
        'radius_m': _radius,
      });
      await api.send('POST', '/alert-subscriptions',
          headers: identity.headers, body: {'saved_location_id': place['id'], 'minimum_severity': 'moderate'});
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = e.isNetwork ? tr(l, 'offline') : e.message;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(tr(l, 'add_place'), style: T.headline),
          const SizedBox(height: 4),
          Text(tr(l, 'add_place_sub'), style: T.body.copyWith(fontSize: 14)),
          const SizedBox(height: 16),
          ClipRRect(
            borderRadius: BorderRadius.circular(20),
            child: SizedBox(
              height: 220,
              child: Stack(children: [
                FlutterMap(
                  mapController: _map,
                  options: MapOptions(
                    initialCenter: _point,
                    initialZoom: _zoom,
                    backgroundColor: const Color(0xFFF2EFE9),
                    interactionOptions: const InteractionOptions(flags: InteractiveFlag.drag | InteractiveFlag.pinchZoom),
                    onPositionChanged: (cam, gesture) {
                      if (gesture) setState(() => _point = cam.center);
                    },
                  ),
                  children: [
                    basemap(context),
                    CircleLayer(circles: [
                      CircleMarker(
                          point: _point,
                          radius: _radius.toDouble(),
                          useRadiusInMeter: true,
                          color: C.brand.withValues(alpha: .12),
                          borderColor: C.brand,
                          borderStrokeWidth: 2),
                    ]),
                  ],
                ),
                IgnorePointer(
                    child: Center(
                        child: Container(
                            width: 18,
                            height: 18,
                            decoration: BoxDecoration(
                                color: C.brand,
                                shape: BoxShape.circle,
                                border: Border.all(color: Colors.white, width: 3),
                                boxShadow: const [BoxShadow(color: Color(0x40121417), blurRadius: 5)])))),
                Positioned(
                    right: 10,
                    bottom: 10,
                    child: MapButton(
                        icon: Icons.my_location_rounded, color: C.location, tooltip: tr(l, 'use_my_location'), onTap: _locate)),
              ]),
            ),
          ),
          const SizedBox(height: 6),
          Text(_located ? tr(l, 'move_map_adjust') : tr(l, 'move_map_place'), style: T.caption),
          const SizedBox(height: 16),
          TextField(
              controller: _name,
              maxLength: 100,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(labelText: tr(l, 'place_name'))),
          const SizedBox(height: 4),
          Text(tr(l, 'warn_me_within'), style: T.label),
          const SizedBox(height: 10),
          ChoiceRow<int>(
            options: const [(500, '500 m'), (1000, '1 km'), (2000, '2 km'), (5000, '5 km')],
            value: _radius,
            onChanged: (v) {
              setState(() => _radius = v);
              try {
                _map.move(_point, _zoom);
              } catch (_) {}
            },
          ),
          if (_error != null)
            Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: T.label.copyWith(color: C.ember))),
          const SizedBox(height: 20),
          FilledButton(
            onPressed: _saving ? null : _save,
            child: _saving
                ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4, color: Colors.white))
                : Text(tr(l, 'save_place')),
          ),
        ]),
      ),
    );
  }
}

/// Language, privacy and version. Small on purpose.
class SettingsSheet extends StatelessWidget {
  const SettingsSheet({super.key});
  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: appState,
        builder: (context, _) {
          final l = appState.lang;
          return SafeArea(
              child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text(tr(l, 'settings'), style: T.headline),
              const SizedBox(height: 18),
              Text(tr(l, 'language'), style: T.label),
              const SizedBox(height: 10),
              Segmented<String>(options: const [('en', 'English'), ('fr', 'Français')], value: l, onChanged: appState.setLang),
              const SizedBox(height: 20),
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(color: C.paper, borderRadius: BorderRadius.circular(18)),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Icon(Icons.visibility_off_rounded, color: C.brand, size: 20),
                  const SizedBox(width: 12),
                  Expanded(child: Text(tr(l, 'privacy_short'), style: T.body.copyWith(fontSize: 14, color: C.ink))),
                ]),
              ),
              const SizedBox(height: 16),
              Row(children: [
                const SisayMark(size: 22),
                const SizedBox(width: 8),
                Text('Sisay $appVersion', style: T.caption),
              ]),
            ]),
          ));
        },
      );
}

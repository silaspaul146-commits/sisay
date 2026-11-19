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

/// Draw a route you take (e.g. Bambili to Bamenda) by tapping along the road. We save the line
/// and warn you about reports near it; we never follow you while you travel.
class RouteEditor extends StatefulWidget {
  const RouteEditor({super.key});
  @override
  State<RouteEditor> createState() => _RouteEditorState();
}

class _RouteEditorState extends State<RouteEditor> {
  final _map = MapController();
  final _name = TextEditingController();
  final List<LatLng> _points = [];
  int _within = 500; // half the corridor
  bool _saving = false;
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
      final p = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(accuracy: LocationAccuracy.medium, timeLimit: Duration(seconds: 15)));
      try {
        _map.move(LatLng(p.latitude, p.longitude), 13.5);
      } catch (_) {}
    } catch (_) {}
  }

  double get _length {
    var m = 0.0;
    for (var k = 1; k < _points.length; k++) {
      m += const Distance().as(LengthUnit.Meter, _points[k - 1], _points[k]);
    }
    return m;
  }

  void _tap(LatLng p) {
    HapticFeedback.selectionClick();
    setState(() => _points.add(p));
  }

  Future<void> _save() async {
    final l = appState.lang;
    if (_points.length < 2 || _name.text.trim().isEmpty) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final route = await api.send('POST', '/saved-routes', headers: identity.headers, body: {
        'name': _name.text.trim(),
        'route': {
          'type': 'LineString',
          'coordinates': [
            for (final p in _points) [p.longitude, p.latitude]
          ]
        },
        'corridor_width_m': _within * 2,
      });
      await api.send('POST', '/alert-subscriptions',
          headers: identity.headers, body: {'saved_route_id': route['id'], 'minimum_severity': 'moderate'});
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
    final canSave = _points.length >= 2 && _name.text.trim().isNotEmpty && !_saving;
    return Scaffold(
      backgroundColor: C.paper,
      appBar: AppBar(
        leading:
            IconButton(icon: const Icon(Icons.close_rounded), tooltip: tr(l, 'cancel'), onPressed: () => Navigator.pop(context)),
        title: Text(tr(l, 'add_route')),
        actions: [
          IconButton(
              onPressed: _points.isEmpty ? null : () => setState(_points.removeLast),
              tooltip: tr(l, 'undo'),
              icon: const Icon(Icons.undo_rounded)),
          IconButton(
              onPressed: _points.isEmpty ? null : () => setState(_points.clear),
              tooltip: tr(l, 'clear'),
              icon: const Icon(Icons.delete_sweep_outlined)),
          const SizedBox(width: 4),
        ],
      ),
      body: Column(children: [
        Expanded(
          child: Stack(children: [
            FlutterMap(
              mapController: _map,
              options: MapOptions(
                initialCenter: const LatLng(defaultLat, defaultLon),
                initialZoom: 12.5,
                backgroundColor: const Color(0xFFF2EFE9),
                interactionOptions: const InteractionOptions(flags: InteractiveFlag.all & ~InteractiveFlag.rotate),
                onTap: (_, p) => _tap(p),
              ),
              children: [
                basemap(context),
                if (_points.length >= 2)
                  PolylineLayer(polylines: [
                    Polyline(points: _points, strokeWidth: 9, color: C.brand.withValues(alpha: .18)),
                    Polyline(
                        points: _points, strokeWidth: 4.5, color: C.brand, borderStrokeWidth: 1.5, borderColor: Colors.white),
                  ]),
                MarkerLayer(markers: [
                  for (var k = 0; k < _points.length; k++)
                    Marker(
                        point: _points[k],
                        width: 26,
                        height: 26,
                        child: _Node(label: k == 0 ? 'A' : (k == _points.length - 1 && _points.length > 1 ? 'B' : null))),
                ]),
              ],
            ),
            Positioned(
                left: 12,
                right: 12,
                top: 12,
                child: Container(
                  padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
                  decoration: BoxDecoration(
                      color: C.ink,
                      borderRadius: BorderRadius.circular(16),
                      boxShadow: const [BoxShadow(color: Color(0x33121417), blurRadius: 12, offset: Offset(0, 4))]),
                  child: Row(children: [
                    const Icon(Icons.touch_app_rounded, color: Colors.white, size: 20),
                    const SizedBox(width: 10),
                    Expanded(
                        child: Text(
                            _points.isEmpty
                                ? tr(l, 'route_hint_start')
                                : _points.length == 1
                                    ? tr(l, 'route_hint_next')
                                    : tr(l, 'route_hint_more'),
                            style:
                                const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w500, height: 1.35))),
                  ]),
                )),
            if (_points.length >= 2)
              Positioned(
                  left: 12,
                  bottom: 12,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(999),
                        boxShadow: const [BoxShadow(color: Color(0x24121417), blurRadius: 10)]),
                    child: Text(distance(_length), style: T.label),
                  )),
          ]),
        ),
        Container(
          decoration: const BoxDecoration(color: Colors.white, border: Border(top: BorderSide(color: C.line))),
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
          child: SafeArea(
            top: false,
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              TextField(
                  controller: _name,
                  maxLength: 100,
                  onChanged: (_) => setState(() {}),
                  textCapitalization: TextCapitalization.sentences,
                  decoration: InputDecoration(labelText: tr(l, 'route_name'), hintText: 'Bambili → Bamenda', counterText: '')),
              const SizedBox(height: 12),
              Text(tr(l, 'warn_me_within_road'), style: T.label),
              const SizedBox(height: 8),
              ChoiceRow<int>(
                  options: const [(250, '250 m'), (500, '500 m'), (1000, '1 km')],
                  value: _within,
                  onChanged: (v) => setState(() => _within = v)),
              if (_error != null)
                Padding(padding: const EdgeInsets.only(top: 10), child: Text(_error!, style: T.label.copyWith(color: C.ember))),
              const SizedBox(height: 14),
              FilledButton(
                onPressed: canSave ? _save : null,
                child: _saving
                    ? const SizedBox(
                        width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4, color: Colors.white))
                    : Text(_points.length < 2 ? tr(l, 'route_need_points') : tr(l, 'save_route')),
              ),
            ]),
          ),
        ),
      ]),
    );
  }
}

class _Node extends StatelessWidget {
  final String? label;
  const _Node({this.label});
  @override
  Widget build(BuildContext context) => label == null
      ? Center(
          child: Container(
              width: 12,
              height: 12,
              decoration:
                  BoxDecoration(color: Colors.white, shape: BoxShape.circle, border: Border.all(color: C.brand, width: 3))))
      : Container(
          decoration: BoxDecoration(
              color: C.ink,
              shape: BoxShape.circle,
              border: Border.all(color: Colors.white, width: 2.5),
              boxShadow: const [BoxShadow(color: Color(0x40121417), blurRadius: 4)]),
          child: Center(
              child: Text(label!, style: const TextStyle(color: Colors.white, fontSize: 11.5, fontWeight: FontWeight.w800))),
        );
}

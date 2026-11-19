import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';

import '../api.dart';
import '../app_state.dart';
import '../config.dart';
import '../identity.dart';
import '../push.dart';
import '../strings.dart';
import '../theme.dart';
import '../widgets.dart';
import 'alerts_screen.dart';
import 'incident_screen.dart';

class PublicIncident {
  final String id, category;
  final String? verification, lifecycle, severity, note, description;
  final LatLng point;
  final int precisionM;
  final DateTime observedAt, updatedAt;
  PublicIncident.fromFeature(Map<String, dynamic> f)
      : id = f['id'] as String,
        category = f['properties']['category'] as String,
        verification = f['properties']['verification_status'] as String?,
        lifecycle = f['properties']['lifecycle'] as String?,
        severity = f['properties']['severity'] as String?,
        note = f['properties']['uncertainty_note'] as String?,
        description = f['properties']['description'] as String?,
        precisionM = (f['properties']['precision_m'] as num?)?.toInt() ?? 0,
        observedAt = DateTime.parse(f['properties']['observed_at'] as String),
        updatedAt = DateTime.parse(f['properties']['last_updated_at'] as String),
        point = LatLng((f['geometry']['coordinates'][1] as num).toDouble(), (f['geometry']['coordinates'][0] as num).toDouble());
}

class MapScreen extends StatefulWidget {
  const MapScreen({super.key});
  @override
  State<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  final _map = MapController();
  List<PublicIncident> _incidents = [];
  Map<String, dynamic>? _alert;
  LatLng? _me;
  bool _offline = false;
  bool _loading = true;
  DateTime? _updated;
  Timer? _debounce;
  double _sheet = 0.3;

  @override
  void initState() {
    super.initState();
    push.received.addListener(_loadAlert);
    _locate(move: true);
    _loadAlert();
  }

  @override
  void dispose() {
    push.received.removeListener(_loadAlert);
    _debounce?.cancel();
    super.dispose();
  }

  Future<void> _locate({bool move = false}) async {
    try {
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
      if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) return;
      final p = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(accuracy: LocationAccuracy.medium, timeLimit: Duration(seconds: 15)));
      if (!mounted) return;
      setState(() => _me = LatLng(p.latitude, p.longitude));
      if (move) {
        try {
          _map.move(_me!, 14);
        } catch (_) {/* map not ready yet */}
      }
    } catch (_) {/* location off: the map stays where it is, panning still works */}
  }

  Future<void> _loadAlert() async {
    if (!await identity.ensureRegistered()) return;
    try {
      final r = await api.send('GET', '/alerts', headers: identity.headers, query: {'limit': '5'});
      final active = (r['items'] as List).cast<Map<String, dynamic>>().where((a) => a['status'] == 'active').toList();
      if (mounted) setState(() => _alert = active.isEmpty ? null : active.first);
    } on ApiException {/* keep last */}
  }

  void _onMoved() {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 500), _load);
  }

  Future<void> _load() async {
    final b = _map.camera.visibleBounds;
    double clamp(double v, double lo, double hi) => v < lo ? lo : (v > hi ? hi : v);
    final c = _map.camera.center;
    final halfW = clamp((b.east - b.west) / 2, 0.01, 0.99), halfH = clamp((b.north - b.south) / 2, 0.01, 0.99);
    final bbox = [c.longitude - halfW, c.latitude - halfH, c.longitude + halfW, c.latitude + halfH]
        .map((v) => v.toStringAsFixed(5))
        .join(',');
    try {
      final r = await api.send('GET', '/public/incidents', query: {'bbox': bbox});
      final list = (r['features'] as List).map((f) => PublicIncident.fromFeature(f as Map<String, dynamic>)).toList();
      if (!mounted) return;
      setState(() {
        _incidents = list;
        _offline = false;
        _loading = false;
        _updated = DateTime.now();
      });
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _offline = e.isNetwork;
          _loading = false;
        });
      }
    }
  }

  Future<void> _refresh() async {
    await Future.wait([_load(), _loadAlert()]);
  }

  void _open(PublicIncident i) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => IncidentScreen(incident: i, from: _me)));

  void _legend() {
    final l = appState.lang;
    Widget row(Widget pin, String title, String body) => Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Row(children: [
            SizedBox(width: 52, child: Center(child: pin)),
            const SizedBox(width: 12),
            Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: T.bodyStrong),
              const SizedBox(height: 2),
              Text(body, style: T.caption.copyWith(color: C.ink2)),
            ])),
          ]),
        );
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
          child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(tr(l, 'legend_title'), style: T.headline),
          const SizedBox(height: 18),
          row(const IncidentPin(category: 'fire', size: 36), tr(l, 'lg_unconfirmed'), tr(l, 'lg_unconfirmed_b')),
          row(const IncidentPin(category: 'fire', verification: 'verified', size: 36), tr(l, 'lg_verified'),
              tr(l, 'lg_verified_b')),
          row(const IncidentPin(category: 'fire', verification: 'disputed', size: 36), tr(l, 'lg_disputed'),
              tr(l, 'lg_disputed_b')),
          row(const IncidentPin(category: 'fire', lifecycle: 'resolved', size: 36), tr(l, 'lg_over'), tr(l, 'lg_over_b')),
          row(const LocationDot(), tr(l, 'lg_you'), tr(l, 'lg_you_b')),
          Text(tr(l, 'unconfirmed_note'), style: T.caption),
        ]),
      )),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final center = _me ?? const LatLng(defaultLat, defaultLon);
    double dist(PublicIncident i) => const Distance().as(LengthUnit.Meter, center, i.point);
    final sorted = [..._incidents]..sort((a, b) => dist(a).compareTo(dist(b)));
    final active = sorted.where((i) => i.lifecycle != 'resolved' && i.lifecycle != 'closed').length;
    final top = MediaQuery.paddingOf(context).top;
    return Stack(children: [
      FlutterMap(
        mapController: _map,
        options: MapOptions(
          initialCenter: const LatLng(defaultLat, defaultLon),
          initialZoom: 13,
          backgroundColor: const Color(0xFFF2EFE9),
          onMapReady: _load,
          onPositionChanged: (_, __) => _onMoved(),
          interactionOptions: const InteractionOptions(flags: InteractiveFlag.all & ~InteractiveFlag.rotate),
        ),
        children: [
          basemap(context),
          MarkerLayer(markers: [
            if (_me != null) Marker(point: _me!, width: 40, height: 40, child: const LocationDot()),
            for (final i in _incidents)
              Marker(
                  point: i.point,
                  width: 84,
                  height: 84,
                  child: GestureDetector(
                      onTap: () => _open(i),
                      child: Center(
                          child: IncidentPin(
                              category: i.category,
                              verification: i.verification,
                              lifecycle: i.lifecycle,
                              fresh: DateTime.now().difference(i.observedAt).inMinutes < 30)))),
          ]),
        ],
      ),
      // soft fade under the status bar so floating cards read cleanly
      IgnorePointer(
          child: Container(
              height: top + 72,
              decoration: const BoxDecoration(
                  gradient: LinearGradient(
                      begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [Color(0xCCF4F2EE), Color(0x00F4F2EE)])))),
      SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              _TopPill(
                live: !_offline,
                text: _offline
                    ? tr(l, 'offline')
                    : _loading
                        ? tr(l, 'loading')
                        : '${tr(l, 'in_view')}: $active',
              ),
              const Spacer(),
              MapButton(icon: Icons.layers_outlined, tooltip: tr(l, 'legend_title'), onTap: _legend),
            ]),
            const SizedBox(height: 10),
            if (_alert != null)
              _AlertCard(
                  alert: _alert!,
                  onTap: () async {
                    await Navigator.of(context)
                        .push(MaterialPageRoute(builder: (_) => AlertDetailScreen(alertId: _alert!['id'] as String)));
                    _loadAlert();
                  }),
          ]),
        ),
      ),
      LayoutBuilder(
          builder: (context, c) => Stack(children: [
                if (_sheet < 0.5)
                  Positioned(
                      right: 16,
                      bottom: c.maxHeight * _sheet + 12,
                      child: MapButton(
                          icon: Icons.near_me_rounded,
                          color: C.location,
                          tooltip: tr(l, 'lg_you'),
                          onTap: () => _locate(move: true))),
                NotificationListener<DraggableScrollableNotification>(
                  onNotification: (n) {
                    if ((n.extent - _sheet).abs() > 0.005) setState(() => _sheet = n.extent);
                    return false;
                  },
                  child: DraggableScrollableSheet(
                    initialChildSize: 0.3,
                    minChildSize: 0.14,
                    maxChildSize: 0.75,
                    snap: true,
                    snapSizes: const [0.3],
                    builder: (context, scroll) => Container(
                      decoration: const BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
                          boxShadow: [BoxShadow(color: Color(0x1F121417), blurRadius: 30, offset: Offset(0, -4))]),
                      child: RefreshIndicator(
                        onRefresh: _refresh,
                        child: ListView(controller: scroll, padding: const EdgeInsets.fromLTRB(20, 10, 20, 20), children: [
                          Center(
                              child: Container(
                                  width: 36,
                                  height: 4,
                                  decoration: BoxDecoration(color: C.line2, borderRadius: BorderRadius.circular(2)))),
                          const SizedBox(height: 14),
                          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                            Expanded(child: Text(tr(l, 'near_you'), style: T.headline)),
                            if (_updated != null) Text('${tr(l, 'updated')} ${ago(_updated!, l)}', style: T.caption),
                          ]),
                          const SizedBox(height: 6),
                          if (sorted.isEmpty && !_loading)
                            Padding(
                              padding: const EdgeInsets.only(top: 8, bottom: 8),
                              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                const IconTile(Icons.wb_twilight_rounded, size: 44),
                                const SizedBox(width: 14),
                                Expanded(
                                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                  Text(tr(l, 'no_reports_title'), style: T.subhead),
                                  const SizedBox(height: 4),
                                  Text(tr(l, 'no_reports_body'), style: T.body.copyWith(fontSize: 14)),
                                ])),
                              ]),
                            ),
                          for (final i in sorted) _IncidentRow(incident: i, meters: dist(i), onTap: () => _open(i)),
                          const SizedBox(height: 12),
                          Row(children: [
                            const Icon(Icons.info_outline_rounded, size: 16, color: C.ink3),
                            const SizedBox(width: 8),
                            Expanded(child: Text(tr(l, 'unconfirmed_note'), style: T.caption)),
                          ]),
                          const SizedBox(height: 6),
                          Text(tileAttribution, style: T.caption.copyWith(fontSize: 11)),
                        ]),
                      ),
                    ),
                  ),
                ),
              ])),
    ]);
  }
}

class _TopPill extends StatelessWidget {
  final bool live;
  final String text;
  const _TopPill({required this.live, required this.text});
  @override
  Widget build(BuildContext context) => Container(
        height: 46,
        padding: const EdgeInsets.fromLTRB(8, 0, 16, 0),
        decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(999),
            boxShadow: const [BoxShadow(color: Color(0x24121417), blurRadius: 12, offset: Offset(0, 3))]),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          const SisayMark(size: 30),
          const SizedBox(width: 10),
          Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(color: live ? const Color(0xFF2EAD62) : C.grey, shape: BoxShape.circle)),
          const SizedBox(width: 8),
          Text(text, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: C.ink)),
        ]),
      );
}

class _AlertCard extends StatelessWidget {
  final Map<String, dynamic> alert;
  final VoidCallback onTap;
  const _AlertCard({required this.alert, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final because = alert['because'] as Map<String, dynamic>?;
    final l = appState.lang;
    return Material(
      color: C.ember,
      borderRadius: BorderRadius.circular(20),
      elevation: 0,
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
          decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(20),
              boxShadow: const [BoxShadow(color: Color(0x40A8350F), blurRadius: 18, offset: Offset(0, 6))]),
          child: Row(children: [
            Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(color: Colors.white.withValues(alpha: .18), shape: BoxShape.circle),
                child: const Icon(Icons.warning_amber_rounded, color: Colors.white, size: 22)),
            const SizedBox(width: 12),
            Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(alert['message'] as String,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 15, height: 1.3)),
              const SizedBox(height: 2),
              Text(
                  [
                    if (because != null) '${because['name']}',
                    ago(DateTime.parse(alert['updated_at'] as String), l),
                  ].join(' · '),
                  style: const TextStyle(color: Color(0xE6FFFFFF), fontSize: 13)),
            ])),
            const Icon(Icons.chevron_right_rounded, color: Colors.white),
          ]),
        ),
      ),
    );
  }
}

class _IncidentRow extends StatelessWidget {
  final PublicIncident incident;
  final double meters;
  final VoidCallback onTap;
  const _IncidentRow({required this.incident, required this.meters, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final i = incident;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(14),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Row(children: [
          IncidentPin(category: i.category, verification: i.verification, lifecycle: i.lifecycle, size: 40),
          const SizedBox(width: 10),
          Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(appState.categoryName(i.category), style: T.bodyStrong.copyWith(fontSize: 16)),
            const SizedBox(height: 2),
            Text('${ago(i.observedAt, l)} · ${distance(meters)}', style: T.caption),
          ])),
          const SizedBox(width: 8),
          StatusChip(statusOf(i.verification, i.lifecycle, l)),
        ]),
      ),
    );
  }
}

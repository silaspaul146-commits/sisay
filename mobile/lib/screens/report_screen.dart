import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';

import '../app_state.dart';
import '../config.dart';
import '../reports_store.dart';
import '../strings.dart';
import '../theme.dart';
import '../widgets.dart';
import 'sent_screen.dart';

/// Report in seconds: tap what's happening, confirm where, send. Only category and location are
/// required (BR-19). The pin marks where it is HAPPENING, not where the reporter stands.
class ReportScreen extends StatefulWidget {
  final String? initialCategory;
  final LatLng? initialPoint;
  const ReportScreen({super.key, this.initialCategory, this.initialPoint});
  @override
  State<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends State<ReportScreen> {
  final _map = MapController();
  final _note = TextEditingController();
  late String? _category = widget.initialCategory;
  bool _showAll = false;
  late LatLng? _point = widget.initialPoint;
  int? _accuracy;
  late String _source = widget.initialPoint != null ? 'manual' : 'gps';
  bool _locating = false;
  bool _sending = false;
  bool _dragging = false;

  @override
  void initState() {
    super.initState();
    if (_point == null) _locate();
  }

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _locate() async {
    setState(() => _locating = true);
    try {
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
      if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) throw Exception('denied');
      final p = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 20)));
      if (!mounted) return;
      setState(() {
        _point = LatLng(p.latitude, p.longitude);
        _accuracy = p.accuracy.round();
        _source = 'gps';
      });
      try {
        _map.move(_point!, 16);
      } catch (_) {/* map not laid out yet: it opens on _point anyway */}
    } catch (_) {
      // keep whatever point we had; the user can move the map instead
    } finally {
      if (mounted) setState(() => _locating = false);
    }
  }

  Future<void> _send() async {
    if (_category == null || _point == null || _sending) return;
    setState(() => _sending = true);
    HapticFeedback.mediumImpact();
    final r = await reportsStore.submit(
        category: _category!,
        lat: _point!.latitude,
        lon: _point!.longitude,
        accuracyM: _source == 'gps' ? _accuracy : 250,
        source: _source,
        note: _note.text);
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => SentScreen(report: r)));
  }

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final cats = appState.categories;
    var shown = _showAll ? cats : cats.take(8).toList();
    if (!_showAll && _category != null && !shown.any((c) => c.code == _category)) {
      shown = [...cats.where((c) => c.code == _category), ...cats.take(7)];
    }
    final ready = _category != null && _point != null;
    final locText = _locating
        ? tr(l, 'finding_location')
        : _point == null
            ? tr(l, 'no_location')
            : _source == 'gps'
                ? '${tr(l, 'your_location')} · ±${_accuracy ?? '?'} m'
                : tr(l, 'pin_placed');
    return Scaffold(
      backgroundColor: C.paper,
      appBar: AppBar(
        leading:
            IconButton(icon: const Icon(Icons.close_rounded), tooltip: tr(l, 'cancel'), onPressed: () => Navigator.pop(context)),
        title: Text(tr(l, 'report_title')),
        actions: [
          Container(
            margin: const EdgeInsets.only(right: 14),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration:
                BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(999), border: Border.all(color: C.line)),
            child: Row(children: [
              const Icon(Icons.visibility_off_rounded, size: 15, color: C.ink2),
              const SizedBox(width: 6),
              Text(tr(l, 'anonymous'), style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: C.ink2)),
            ]),
          ),
        ],
      ),
      body: ListView(
          physics: _dragging ? const NeverScrollableScrollPhysics() : null,
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
          children: [
            _StepTitle(n: 1, text: tr(l, 'whats_happening'), done: _category != null),
            const SizedBox(height: 12),
            GridView.count(
              crossAxisCount: 4,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 8,
              crossAxisSpacing: 8,
              childAspectRatio: .82,
              children: [
                for (final c in shown)
                  _CategoryTile(
                      code: c.code,
                      label: appState.categoryName(c.code),
                      selected: _category == c.code,
                      onTap: () {
                        HapticFeedback.selectionClick();
                        setState(() => _category = c.code);
                      }),
              ],
            ),
            if (!_showAll)
              Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: () => setState(() => _showAll = true),
                    icon: const Icon(Icons.expand_more_rounded),
                    label: Text(tr(l, 'more_types')),
                  )),
            const SizedBox(height: 14),
            _StepTitle(n: 2, text: tr(l, 'where'), done: _point != null),
            const SizedBox(height: 12),
            ClipRRect(
              borderRadius: BorderRadius.circular(20),
              child: Container(
                decoration: BoxDecoration(
                    color: Colors.white, border: Border.all(color: C.line), borderRadius: BorderRadius.circular(20)),
                child: Column(children: [
                  SizedBox(
                    height: 200,
                    child: Listener(
                      onPointerDown: (_) => setState(() => _dragging = true),
                      onPointerUp: (_) => setState(() => _dragging = false),
                      onPointerCancel: (_) => setState(() => _dragging = false),
                      child: Stack(children: [
                        FlutterMap(
                          mapController: _map,
                          options: MapOptions(
                            initialCenter: _point ?? const LatLng(defaultLat, defaultLon),
                            initialZoom: _point == null ? 13 : 16,
                            backgroundColor: const Color(0xFFF2EFE9),
                            interactionOptions: const InteractionOptions(flags: InteractiveFlag.drag | InteractiveFlag.pinchZoom),
                            onPositionChanged: (camera, hasGesture) {
                              if (hasGesture) {
                                setState(() {
                                  _point = camera.center;
                                  _source = 'manual';
                                });
                              }
                            },
                          ),
                          children: [basemap(context)],
                        ),
                        IgnorePointer(
                            child: Center(
                                child: AnimatedSlide(
                          duration: const Duration(milliseconds: 150),
                          offset: Offset(0, _dragging ? -.62 : -.5),
                          child: const _DropPin(),
                        ))),
                        IgnorePointer(
                            child: Center(
                                child: Container(
                                    width: 8,
                                    height: 4,
                                    decoration:
                                        BoxDecoration(color: const Color(0x55121417), borderRadius: BorderRadius.circular(4))))),
                      ]),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(14, 10, 6, 10),
                    child: Row(children: [
                      Icon(_source == 'gps' ? Icons.my_location_rounded : Icons.push_pin_outlined,
                          size: 18, color: _point == null ? C.ember : C.ink2),
                      const SizedBox(width: 8),
                      Expanded(child: Text(locText, style: const TextStyle(fontSize: 14, color: C.ink2))),
                      TextButton(onPressed: _locating ? null : _locate, child: Text(tr(l, 'use_my_location'))),
                    ]),
                  ),
                ]),
              ),
            ),
            const SizedBox(height: 8),
            Padding(padding: const EdgeInsets.symmetric(horizontal: 4), child: Text(tr(l, 'pin_hint'), style: T.caption)),
            const SizedBox(height: 18),
            _StepTitle(n: 3, text: tr(l, 'add_note'), done: false, optional: true),
            const SizedBox(height: 12),
            TextField(
                controller: _note,
                maxLines: 3,
                maxLength: 2000,
                textCapitalization: TextCapitalization.sentences,
                decoration: InputDecoration(hintText: tr(l, 'note_hint'))),
          ]),
      bottomNavigationBar: Container(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 10),
        decoration: const BoxDecoration(color: Colors.white, border: Border(top: BorderSide(color: C.line))),
        child: SafeArea(
          top: false,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            SizedBox(
                width: double.infinity,
                child: FilledButton(
                  style: FilledButton.styleFrom(backgroundColor: C.ember),
                  onPressed: ready && !_sending ? _send : null,
                  child: _sending
                      ? const SizedBox(
                          width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4, color: Colors.white))
                      : Text(ready ? tr(l, 'send') : (_category == null ? tr(l, 'choose_first') : tr(l, 'choose_place'))),
                )),
            const SizedBox(height: 8),
            Text(tr(l, 'no_account_needed'), style: T.caption.copyWith(fontSize: 12)),
          ]),
        ),
      ),
    );
  }
}

class _StepTitle extends StatelessWidget {
  final int n;
  final String text;
  final bool done, optional;
  const _StepTitle({required this.n, required this.text, required this.done, this.optional = false});
  @override
  Widget build(BuildContext context) => Row(children: [
        AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          width: 26,
          height: 26,
          decoration: BoxDecoration(
              color: done ? C.ink : Colors.white,
              shape: BoxShape.circle,
              border: Border.all(color: done ? C.ink : C.line2, width: 1.5)),
          child: Center(
              child: done
                  ? const Icon(Icons.check_rounded, size: 16, color: Colors.white)
                  : Text('$n', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: C.ink2))),
        ),
        const SizedBox(width: 10),
        Text(text, style: T.subhead.copyWith(fontSize: 17)),
      ]);
}

class _DropPin extends StatelessWidget {
  const _DropPin();
  @override
  Widget build(BuildContext context) => SizedBox(
        width: 44,
        height: 56,
        child: Stack(alignment: Alignment.topCenter, children: [
          Positioned(
              top: 30,
              child: Container(
                  width: 4, height: 24, decoration: BoxDecoration(color: C.ink, borderRadius: BorderRadius.circular(2)))),
          Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(
                  color: C.ember,
                  shape: BoxShape.circle,
                  border: Border.all(color: Colors.white, width: 3),
                  boxShadow: const [BoxShadow(color: Color(0x40121417), blurRadius: 8, offset: Offset(0, 3))])),
        ]),
      );
}

class _CategoryTile extends StatelessWidget {
  final String code, label;
  final bool selected;
  final VoidCallback onTap;
  const _CategoryTile({required this.code, required this.label, required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) => Semantics(
        selected: selected,
        button: true,
        label: label,
        excludeSemantics: true,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          decoration: BoxDecoration(
            color: selected ? C.ink : Colors.white,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: selected ? C.ink : C.line),
          ),
          child: Material(
            type: MaterialType.transparency,
            child: InkWell(
              borderRadius: BorderRadius.circular(18),
              onTap: onTap,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(4, 10, 4, 8),
                child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Icon(categoryIcon(code), size: 26, color: selected ? Colors.white : C.ink),
                  const SizedBox(height: 8),
                  Text(label,
                      textAlign: TextAlign.center,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          fontSize: 12, fontWeight: FontWeight.w600, height: 1.2, color: selected ? Colors.white : C.ink)),
                ]),
              ),
            ),
          ),
        ),
      );
}

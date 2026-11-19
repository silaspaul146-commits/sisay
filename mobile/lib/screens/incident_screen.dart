import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../api.dart';
import '../app_state.dart';
import '../config.dart';
import '../strings.dart';
import '../theme.dart';
import '../widgets.dart';
import 'map_screen.dart';
import 'report_screen.dart';

/// One public incident, in plain words: what, how sure we are, when, roughly where (the exact
/// spot is hidden on purpose), and what you can do.
class IncidentScreen extends StatefulWidget {
  final PublicIncident incident;
  final LatLng? from;
  const IncidentScreen({super.key, required this.incident, this.from});
  @override
  State<IncidentScreen> createState() => _IncidentScreenState();
}

class _IncidentScreenState extends State<IncidentScreen> {
  late PublicIncident _i = widget.incident;
  bool _gone = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final f = await api.send('GET', '/public/incidents/${widget.incident.id}');
      if (mounted) setState(() => _i = PublicIncident.fromFeature(f as Map<String, dynamic>));
    } on ApiException catch (e) {
      if (e.status == 404 && mounted) setState(() => _gone = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final i = _i;
    final status = statusOf(i.verification, i.lifecycle, l);
    final over = i.lifecycle == 'resolved' || i.lifecycle == 'closed';
    final meters = widget.from == null ? null : const Distance().as(LengthUnit.Meter, widget.from!, i.point);
    final explain = over
        ? tr(l, 'ex_over')
        : switch (i.verification) {
            'verified' => tr(l, 'ex_verified'),
            'disputed' => tr(l, 'ex_disputed'),
            'under_review' => tr(l, 'ex_review'),
            _ => tr(l, 'ex_unconfirmed'),
          };
    return Scaffold(
      backgroundColor: C.paper,
      body: CustomScrollView(slivers: [
        SliverAppBar(
          pinned: true,
          expandedHeight: 260,
          backgroundColor: C.paper,
          leading: Padding(
              padding: const EdgeInsets.all(6),
              child: MapButton(
                  icon: Icons.arrow_back_rounded,
                  tooltip: MaterialLocalizations.of(context).backButtonTooltip,
                  onTap: () => Navigator.pop(context))),
          flexibleSpace: FlexibleSpaceBar(
            background: IgnorePointer(
                child: FlutterMap(
              options: MapOptions(
                  initialCenter: i.point,
                  initialZoom: i.precisionM > 1500 ? 12.5 : 14.5,
                  backgroundColor: const Color(0xFFF2EFE9),
                  interactionOptions: const InteractionOptions(flags: InteractiveFlag.none)),
              children: [
                basemap(context),
                CircleLayer(circles: [
                  CircleMarker(
                      point: i.point,
                      radius: i.precisionM.toDouble().clamp(150, 5000),
                      useRadiusInMeter: true,
                      color: (over ? C.grey : C.amber).withValues(alpha: .14),
                      borderColor: (over ? C.grey : C.amber).withValues(alpha: .6),
                      borderStrokeWidth: 1.5),
                ]),
                MarkerLayer(markers: [
                  Marker(
                      point: i.point,
                      width: 72,
                      height: 72,
                      child: Center(
                          child:
                              IncidentPin(category: i.category, verification: i.verification, lifecycle: i.lifecycle, size: 46))),
                ]),
              ],
            )),
          ),
        ),
        SliverToBoxAdapter(
            child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 32),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (_gone)
              Container(
                margin: const EdgeInsets.only(bottom: 16),
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(color: C.greyTint, borderRadius: BorderRadius.circular(16)),
                child: Text(tr(l, 'incident_gone'), style: T.body),
              ),
            StatusChip(status),
            const SizedBox(height: 12),
            Text(appState.categoryName(i.category), style: T.title),
            const SizedBox(height: 6),
            Text(
                [
                  '${tr(l, 'reported')} ${ago(i.observedAt, l)}',
                  if (meters != null) '${distance(meters)} ${tr(l, 'from_you')}',
                ].join(' · '),
                style: T.body),
            const SizedBox(height: 20),
            SCard(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tr(l, 'how_sure'), style: T.overline),
                const SizedBox(height: 8),
                Text(explain, style: T.body.copyWith(color: C.ink)),
                if (i.note != null && i.note!.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text(i.note!, style: T.body.copyWith(fontSize: 14)),
                ],
              ]),
            ),
            if (i.description != null && i.description!.trim().isNotEmpty) ...[
              const SizedBox(height: 12),
              SCard(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(tr(l, 'what_people_say'), style: T.overline),
                  const SizedBox(height: 8),
                  Text(i.description!, style: T.body.copyWith(color: C.ink)),
                ]),
              ),
            ],
            const SizedBox(height: 12),
            SCard(
              padding: EdgeInsets.zero,
              child: Column(children: [
                _Fact(icon: Icons.schedule_rounded, label: tr(l, 'first_reported'), value: _when(i.observedAt, l)),
                const Divider(indent: 56),
                _Fact(icon: Icons.update_rounded, label: tr(l, 'last_update'), value: ago(i.updatedAt, l)),
                const Divider(indent: 56),
                _Fact(
                    icon: Icons.blur_circular_rounded,
                    label: tr(l, 'where_roughly'),
                    value: '${tr(l, 'within_about')} ${distance(i.precisionM.toDouble())}',
                    hint: tr(l, 'exact_hidden')),
              ]),
            ),
            if (!over) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(color: C.brandWash, borderRadius: BorderRadius.circular(20)),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Icon(Icons.tips_and_updates_outlined, color: C.brand, size: 22),
                  const SizedBox(width: 12),
                  Expanded(child: Text(tr(l, 'advice'), style: T.body.copyWith(color: C.ink))),
                ]),
              ),
            ],
            const SizedBox(height: 24),
            OutlinedButton.icon(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                  fullscreenDialog: true, builder: (_) => ReportScreen(initialCategory: i.category, initialPoint: i.point))),
              icon: const Icon(Icons.campaign_outlined),
              label: Text(tr(l, 'i_see_this')),
            ),
            const SizedBox(height: 14),
            Text(tr(l, 'unconfirmed_note'), style: T.caption),
          ]),
        )),
      ]),
    );
  }

  static String _when(DateTime t, String l) {
    final d = t.toLocal();
    String two(int v) => v.toString().padLeft(2, '0');
    final today = DateTime.now();
    final sameDay = d.year == today.year && d.month == today.month && d.day == today.day;
    final time = '${two(d.hour)}:${two(d.minute)}';
    if (sameDay) return '${l == 'fr' ? "Aujourd'hui" : 'Today'}, $time';
    return '${two(d.day)}/${two(d.month)}, $time';
  }
}

class _Fact extends StatelessWidget {
  final IconData icon;
  final String label, value;
  final String? hint;
  const _Fact({required this.icon, required this.label, required this.value, this.hint});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, size: 22, color: C.ink3),
          const SizedBox(width: 18),
          Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, style: T.caption),
            const SizedBox(height: 2),
            Text(value, style: T.bodyStrong),
            if (hint != null) ...[const SizedBox(height: 2), Text(hint!, style: T.caption)],
          ])),
        ]),
      );
}

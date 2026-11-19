import 'package:flutter/material.dart';

import '../api.dart';
import '../app_state.dart';
import '../identity.dart';
import '../push.dart';
import '../strings.dart';
import '../theme.dart';
import '../widgets.dart';

class AlertsScreen extends StatefulWidget {
  const AlertsScreen({super.key});
  @override
  State<AlertsScreen> createState() => _AlertsScreenState();
}

class _AlertsScreenState extends State<AlertsScreen> {
  List<Map<String, dynamic>>? _items;
  String? _error;

  @override
  void initState() {
    super.initState();
    push.received.addListener(_load);
    _load();
  }

  @override
  void dispose() {
    push.received.removeListener(_load);
    super.dispose();
  }

  Future<void> _load() async {
    if (!await identity.ensureRegistered()) {
      if (mounted) setState(() => _error = tr(appState.lang, 'offline'));
      return;
    }
    try {
      final r = await api.send('GET', '/alerts', headers: identity.headers, query: {'limit': '50'});
      if (mounted) {
        setState(() {
          _items = (r['items'] as List).cast<Map<String, dynamic>>();
          _error = null;
        });
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.isNetwork ? tr(appState.lang, 'offline') : e.message);
    }
  }

  Future<void> _open(Map<String, dynamic> a) async {
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => AlertDetailScreen(alertId: a['id'] as String)));
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final items = _items ?? const <Map<String, dynamic>>[];
    final now = items.where((a) => a['status'] == 'active').toList();
    final earlier = items.where((a) => a['status'] != 'active').toList();
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: RefreshIndicator(
          onRefresh: _load,
          child: ListView(padding: const EdgeInsets.only(bottom: 24), children: [
            PageHeader(tr(l, 'alerts_title'), subtitle: tr(l, 'alerts_sub')),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                if (_error != null) _ErrorLine(_error!),
                if (_items == null && _error == null)
                  const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator())),
                if (_items != null && items.isEmpty)
                  EmptyState(icon: Icons.notifications_none_rounded, title: tr(l, 'no_alerts'), body: tr(l, 'no_alerts_body')),
                if (now.isNotEmpty) ...[
                  SectionLabel(tr(l, 'now')),
                  for (final a in now)
                    Padding(padding: const EdgeInsets.only(bottom: 10), child: _AlertCard(a: a, onTap: () => _open(a))),
                ],
                if (earlier.isNotEmpty) ...[
                  SectionLabel(tr(l, 'earlier')),
                  SCard(
                    padding: EdgeInsets.zero,
                    child: Column(children: [
                      for (var k = 0; k < earlier.length; k++) ...[
                        if (k > 0) const Divider(indent: 68),
                        _AlertRow(a: earlier[k], onTap: () => _open(earlier[k])),
                      ],
                    ]),
                  ),
                ],
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

class _ErrorLine extends StatelessWidget {
  final String text;
  const _ErrorLine(this.text);
  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(top: 12),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(color: C.sunk, borderRadius: BorderRadius.circular(14)),
        child: Row(children: [
          const Icon(Icons.cloud_off_rounded, size: 18, color: C.ink2),
          const SizedBox(width: 10),
          Expanded(child: Text(text, style: T.label.copyWith(color: C.ink2))),
        ]),
      );
}

String _becauseLine(Map<String, dynamic> a, String l) {
  final because = a['because'] as Map<String, dynamic>?;
  return [
    if (because != null) '${because['kind'] == 'route' ? tr(l, 'on_route') : tr(l, 'near_place')} ${because['name']}',
    ago(DateTime.parse(a['updated_at'] as String), l),
  ].join(' · ');
}

/// Active alerts: a card that is hard to miss, but not alarming for its own sake.
class _AlertCard extends StatelessWidget {
  final Map<String, dynamic> a;
  final VoidCallback onTap;
  const _AlertCard({required this.a, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final unread = a['acknowledged'] != true;
    return Material(
      color: Colors.white,
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: BorderSide(color: unread ? C.ember.withValues(alpha: .45) : C.line, width: unread ? 1.5 : 1)),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: IntrinsicHeight(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Container(width: 5, color: C.ember),
            Expanded(
                child: Padding(
              padding: const EdgeInsets.fromLTRB(14, 14, 12, 14),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                IncidentPin(
                    category: a['category'] as String? ?? 'other', verification: a['verification_status'] as String?, size: 40),
                const SizedBox(width: 10),
                Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(a['message'] as String, style: T.bodyStrong.copyWith(fontSize: 15.5, height: 1.3)),
                  const SizedBox(height: 6),
                  Text(_becauseLine(a, l), style: T.caption),
                ])),
                if (unread)
                  Container(
                      margin: const EdgeInsets.only(top: 4, left: 6),
                      width: 9,
                      height: 9,
                      decoration: const BoxDecoration(color: C.ember, shape: BoxShape.circle)),
              ]),
            )),
          ]),
        ),
      ),
    );
  }
}

class _AlertRow extends StatelessWidget {
  final Map<String, dynamic> a;
  final VoidCallback onTap;
  const _AlertRow({required this.a, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          IncidentPin(category: a['category'] as String? ?? 'other', lifecycle: 'resolved', size: 40),
          const SizedBox(width: 10),
          Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(a['message'] as String,
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: C.ink2, height: 1.3)),
            const SizedBox(height: 4),
            Text(_becauseLine(a, l), style: T.caption),
          ])),
        ]),
      ),
    );
  }
}

class AlertDetailScreen extends StatefulWidget {
  final String alertId;
  const AlertDetailScreen({super.key, required this.alertId});
  @override
  State<AlertDetailScreen> createState() => _AlertDetailScreenState();
}

class _AlertDetailScreenState extends State<AlertDetailScreen> {
  Map<String, dynamic>? _a;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final a = await api.send('GET', '/alerts/${widget.alertId}', headers: identity.headers);
      if (mounted) setState(() => _a = a as Map<String, dynamic>);
      api.send('POST', '/alerts/${widget.alertId}/acknowledgements', headers: identity.headers).ignore();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final a = _a;
    final active = a?['status'] == 'active';
    final fg = active ? Colors.white : C.ink;
    return Scaffold(
      backgroundColor: C.paper,
      appBar: AppBar(
          backgroundColor: active ? C.ember : C.paper,
          foregroundColor: fg,
          title: Text(l == 'fr' ? 'Alerte' : 'Alert', style: T.subhead.copyWith(color: fg, fontSize: 18))),
      body: a == null
          ? Center(child: _error != null ? Text(_error!) : const CircularProgressIndicator())
          : ListView(padding: EdgeInsets.zero, children: [
              Container(
                color: active ? C.ember : C.paper,
                padding: const EdgeInsets.fromLTRB(20, 4, 20, 26),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(a['message'] as String, style: T.title.copyWith(color: fg, fontSize: 27)),
                  const SizedBox(height: 14),
                  Wrap(spacing: 10, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                    StatusChip(statusOf(a['verification_status'] as String?, active ? null : 'resolved', l), onDark: active),
                    Text(ago(DateTime.parse(a['issued_at'] as String), l),
                        style: TextStyle(color: active ? const Color(0xE6FFFFFF) : C.ink3, fontWeight: FontWeight.w600)),
                  ]),
                ]),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  SCard(child: Text(a['uncertainty'] as String, style: T.body.copyWith(color: C.ink))),
                  if (a['because'] != null) ...[
                    const SizedBox(height: 10),
                    SCard(
                      child: Row(children: [
                        IconTile(a['because']['kind'] == 'route' ? Icons.route_rounded : Icons.place_rounded, size: 40),
                        const SizedBox(width: 12),
                        Expanded(
                            child: Text(
                                '${a['because']['kind'] == 'route' ? tr(l, 'because_route') : tr(l, 'because_place')} "${a['because']['name']}".',
                                style: T.body.copyWith(color: C.ink))),
                      ]),
                    ),
                  ],
                  if (active) ...[
                    const SizedBox(height: 10),
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
                  SectionLabel(tr(l, 'updates')),
                  SCard(
                    child: Column(children: [
                      for (final (k, u) in (a['updates'] as List).reversed.indexed)
                        _TimelineItem(
                            time: ago(DateTime.parse(u['received_at'] as String), l),
                            text: u['message'] as String,
                            first: k == 0,
                            last: k == (a['updates'] as List).length - 1),
                    ]),
                  ),
                ]),
              ),
            ]),
    );
  }
}

class _TimelineItem extends StatelessWidget {
  final String time, text;
  final bool first, last;
  const _TimelineItem({required this.time, required this.text, required this.first, required this.last});
  @override
  Widget build(BuildContext context) => IntrinsicHeight(
        child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SizedBox(
              width: 20,
              child: Column(children: [
                const SizedBox(height: 4),
                Container(
                    width: 10,
                    height: 10,
                    decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: first ? C.ink : Colors.white,
                        border: Border.all(color: first ? C.ink : C.line2, width: 2))),
                if (!last) Expanded(child: Container(width: 2, color: C.line)),
              ])),
          const SizedBox(width: 10),
          Expanded(
              child: Padding(
            padding: EdgeInsets.only(bottom: last ? 0 : 16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(text,
                  style: TextStyle(
                      fontSize: 14.5,
                      height: 1.4,
                      color: first ? C.ink : C.ink2,
                      fontWeight: first ? FontWeight.w600 : FontWeight.w400)),
              const SizedBox(height: 2),
              Text(time, style: T.caption.copyWith(fontSize: 12)),
            ]),
          )),
        ]),
      );
}

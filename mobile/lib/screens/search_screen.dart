import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api.dart';
import '../app_state.dart';
import '../strings.dart';
import '../theme.dart';
import '../widgets.dart';

class FoundPlace {
  final String name;
  final String detail;
  final double lat;
  final double lon;
  final String kind;
  final List<double>? bbox; // west, south, east, north
  const FoundPlace(this.name, this.detail, this.lat, this.lon, this.kind, this.bbox);

  factory FoundPlace.fromJson(Map<String, dynamic> j) => FoundPlace(
        j['name'] as String,
        (j['detail'] as String?) ?? '',
        (j['latitude'] as num).toDouble(),
        (j['longitude'] as num).toDouble(),
        (j['kind'] as String?) ?? 'place',
        (j['bbox'] as List?)?.map((e) => (e as num).toDouble()).toList(),
      );

  Map<String, dynamic> toJson() =>
      {'name': name, 'detail': detail, 'latitude': lat, 'longitude': lon, 'kind': kind, 'bbox': bbox};
}

/// Find a town, neighbourhood or road and move the map there. Searches run when you press
/// search (not on every letter) and go through our server; recent picks stay on this phone only.
class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});
  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  final _q = TextEditingController();
  List<FoundPlace>? _results;
  List<FoundPlace> _recent = [];
  bool _busy = false;
  String? _error;

  static const _recentKey = 'recent_places';

  @override
  void initState() {
    super.initState();
    _loadRecent();
  }

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Future<void> _loadRecent() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getStringList(_recentKey) ?? const [];
      final list = <FoundPlace>[];
      for (final r in raw) {
        try {
          list.add(FoundPlace.fromJson(Map<String, dynamic>.from(jsonDecode(r) as Map)));
        } catch (_) {}
      }
      if (mounted) setState(() => _recent = list);
    } catch (_) {}
  }

  Future<void> _remember(FoundPlace p) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final list = [p, ..._recent.where((r) => r.name != p.name || r.detail != p.detail)].take(6).toList();
      await prefs.setStringList(_recentKey, [for (final r in list) jsonEncode(r.toJson())]);
    } catch (_) {}
  }

  Future<void> _clearRecent() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_recentKey);
    } catch (_) {}
    setState(() => _recent = []);
  }

  Future<void> _search() async {
    final q = _q.text.trim();
    if (q.length < 2 || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final r = await api.send('POST', '/public/place-search', body: {'query': q, 'lang': appState.lang});
      final items = (r['items'] as List).cast<Map<String, dynamic>>().map(FoundPlace.fromJson).toList();
      if (mounted) setState(() => _results = items);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _error = e.isNetwork
            ? tr(appState.lang, 'search_offline')
            : e.status == 503
                ? tr(appState.lang, 'search_down')
                : tr(appState.lang, 'error_generic'));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _pick(FoundPlace p) {
    HapticFeedback.selectionClick();
    _remember(p);
    Navigator.pop(context, p);
  }

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final showRecent = _results == null && _error == null && _recent.isNotEmpty;
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: Padding(
          padding: const EdgeInsets.only(right: 12),
          child: TextField(
            controller: _q,
            autofocus: true,
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => _search(),
            onChanged: (_) => setState(() {}),
            style: T.bodyStrong,
            decoration: InputDecoration(
              hintText: tr(l, 'search_hint'),
              isDense: true,
              prefixIcon: const Icon(Icons.search_rounded, color: C.ink3),
              suffixIcon: _q.text.isEmpty
                  ? null
                  : IconButton(
                      tooltip: tr(l, 'clear'),
                      icon: const Icon(Icons.close_rounded, size: 20, color: C.ink3),
                      onPressed: () => setState(() {
                            _q.clear();
                            _results = null;
                            _error = null;
                          })),
            ),
          ),
        ),
      ),
      body: ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 32), children: [
        if (_busy) const LinearProgressIndicator(minHeight: 2),
        if (_q.text.trim().length >= 2 && _results == null && !_busy && _error == null)
          Padding(
            padding: const EdgeInsets.only(top: 4, bottom: 8),
            child: FilledButton.icon(
                onPressed: _search,
                icon: const Icon(Icons.search_rounded),
                label: Text('${tr(l, 'search_for')} "${_q.text.trim()}"', overflow: TextOverflow.ellipsis)),
          ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 16),
            child: EmptyState(icon: Icons.wifi_off_rounded, title: _error!, body: tr(l, 'search_pan_instead')),
          ),
        if (_results != null && _results!.isEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 16),
            child: EmptyState(icon: Icons.search_off_rounded, title: tr(l, 'search_none'), body: tr(l, 'search_none_body')),
          ),
        if (_results != null && _results!.isNotEmpty) ...[
          SectionLabel(tr(l, 'search_results')),
          _List(items: _results!, onPick: _pick),
          const SizedBox(height: 10),
          Text('© OpenStreetMap contributors', style: T.caption.copyWith(fontSize: 11)),
        ],
        if (showRecent) ...[
          SectionLabel(tr(l, 'search_recent'), trailing: TextButton(onPressed: _clearRecent, child: Text(tr(l, 'clear')))),
          _List(items: _recent, onPick: _pick, recent: true),
          const SizedBox(height: 10),
          Row(children: [
            const Icon(Icons.lock_outline_rounded, size: 15, color: C.ink3),
            const SizedBox(width: 8),
            Expanded(child: Text(tr(l, 'search_recent_private'), style: T.caption)),
          ]),
        ],
        if (_results == null && _error == null && _recent.isEmpty && _q.text.trim().length < 2)
          Padding(
            padding: const EdgeInsets.only(top: 24),
            child: EmptyState(icon: Icons.travel_explore_rounded, title: tr(l, 'search_title'), body: tr(l, 'search_body')),
          ),
      ]),
    );
  }
}

class _List extends StatelessWidget {
  final List<FoundPlace> items;
  final void Function(FoundPlace) onPick;
  final bool recent;
  const _List({required this.items, required this.onPick, this.recent = false});

  IconData _icon(FoundPlace p) => recent
      ? Icons.history_rounded
      : switch (p.kind) {
          'town' => Icons.location_city_rounded,
          'neighbourhood' => Icons.holiday_village_rounded,
          'road' => Icons.add_road_rounded,
          'area' => Icons.map_outlined,
          _ => Icons.place_outlined,
        };

  @override
  Widget build(BuildContext context) => SCard(
        padding: EdgeInsets.zero,
        child: Column(children: [
          for (var k = 0; k < items.length; k++) ...[
            if (k > 0) const Divider(indent: 64),
            InkWell(
              onTap: () => onPick(items[k]),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
                child: Row(children: [
                  IconTile(_icon(items[k]), fg: recent ? C.ink2 : C.brand, bg: recent ? C.sunk : C.brandTint, size: 40),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(items[k].name, style: T.bodyStrong, maxLines: 1, overflow: TextOverflow.ellipsis),
                      if (items[k].detail.isNotEmpty)
                        Text(items[k].detail, style: T.caption, maxLines: 1, overflow: TextOverflow.ellipsis),
                    ]),
                  ),
                  const Icon(Icons.north_west_rounded, size: 18, color: C.ink3),
                ]),
              ),
            ),
          ],
        ]),
      );
}

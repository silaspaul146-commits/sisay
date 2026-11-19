import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app_state.dart';
import '../push.dart';
import '../strings.dart';
import '../theme.dart';
import 'alerts_screen.dart';
import 'map_screen.dart';
import 'my_reports_screen.dart';
import 'places_screen.dart';
import 'report_screen.dart';

class Shell extends StatefulWidget {
  final int initialTab;
  const Shell({super.key, this.initialTab = 0});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  late int _tab = widget.initialTab;
  static const _pages = [MapScreen(), AlertsScreen(), PlacesScreen(), MyReportsScreen()];
  Timer? _bannerTimer;

  @override
  void initState() {
    super.initState();
    push.openAlert = (id) {
      if (!mounted) return;
      setState(() => _tab = 1);
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => AlertDetailScreen(alertId: id)));
    };
    push.addListener(_onPush);
    WidgetsBinding.instance.addPostFrameCallback((_) => push.shellReady());
  }

  @override
  void dispose() {
    push.removeListener(_onPush);
    push.openAlert = null;
    _bannerTimer?.cancel();
    super.dispose();
  }

  void _onPush() {
    if (!mounted) return;
    setState(() {});
    _bannerTimer?.cancel();
    if (push.latest != null) _bannerTimer = Timer(const Duration(seconds: 10), push.dismissLatest);
  }

  void _report() {
    HapticFeedback.lightImpact();
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ReportScreen(), fullscreenDialog: true));
  }

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    Widget item(int index, IconData icon, IconData active, String label) {
      final on = _tab == index;
      return Expanded(
        child: Semantics(
          selected: on,
          button: true,
          label: label,
          excludeSemantics: true,
          child: InkResponse(
              onTap: () {
                if (_tab != index) HapticFeedback.selectionClick();
                setState(() => _tab = index);
              },
              radius: 36,
              child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                Icon(on ? active : icon, size: 25, color: on ? C.ink : C.ink3),
                const SizedBox(height: 4),
                Text(label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                        fontSize: 11.5, fontWeight: on ? FontWeight.w700 : FontWeight.w500, color: on ? C.ink : C.ink3)),
              ])),
        ),
      );
    }

    return Scaffold(
      body: Stack(children: [
        IndexedStack(index: _tab, children: _pages),
        Positioned(
          left: 12,
          right: 12,
          top: 0,
          child: SafeArea(
            bottom: false,
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 260),
              transitionBuilder: (child, a) => SlideTransition(
                  position: Tween(begin: const Offset(0, -1.2), end: Offset.zero)
                      .animate(CurvedAnimation(parent: a, curve: Curves.easeOutCubic)),
                  child: child),
              child: push.latest == null
                  ? const SizedBox.shrink()
                  : _LiveBanner(
                      key: ValueKey(push.latest!.messageId),
                      title: push.latest!.notification?.title ?? tr(l, 'new_alert'),
                      body: push.latest!.notification?.body,
                      action: tr(l, 'view'),
                      onTap: push.openLatest,
                      onDismiss: push.dismissLatest,
                    ),
            ),
          ),
        ),
      ]),
      bottomNavigationBar: Container(
        decoration: const BoxDecoration(color: Colors.white, border: Border(top: BorderSide(color: C.line))),
        child: SafeArea(
          top: false,
          child: SizedBox(
            height: 66,
            child: Row(children: [
              item(0, Icons.map_outlined, Icons.map_rounded, tr(l, 'nav_map')),
              item(1, Icons.notifications_none_rounded, Icons.notifications_rounded, tr(l, 'nav_alerts')),
              Expanded(
                child: Semantics(
                    button: true,
                    label: tr(l, 'nav_report'),
                    excludeSemantics: true,
                    child: InkResponse(
                      onTap: _report,
                      radius: 36,
                      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                        Container(
                          width: 54,
                          height: 32,
                          decoration: BoxDecoration(color: C.ember, borderRadius: BorderRadius.circular(12)),
                          child: const Icon(Icons.add_rounded, color: Colors.white, size: 24),
                        ),
                        const SizedBox(height: 4),
                        Text(tr(l, 'nav_report'),
                            style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: C.ink)),
                      ]),
                    )),
              ),
              item(2, Icons.bookmark_border_rounded, Icons.bookmark_rounded, tr(l, 'nav_places')),
              item(3, Icons.inbox_outlined, Icons.inbox_rounded, tr(l, 'nav_mine_short')),
            ]),
          ),
        ),
      ),
    );
  }
}

/// An alert that arrived while the app is open. Android does not show it in the tray then, so we do.
class _LiveBanner extends StatelessWidget {
  final String title;
  final String? body;
  final String action;
  final VoidCallback onTap;
  final VoidCallback onDismiss;
  const _LiveBanner(
      {super.key, required this.title, this.body, required this.action, required this.onTap, required this.onDismiss});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Dismissible(
          key: const ValueKey('live-banner'),
          direction: DismissDirection.up,
          onDismissed: (_) => onDismiss(),
          child: Material(
            color: C.ink,
            elevation: 0,
            borderRadius: BorderRadius.circular(18),
            child: InkWell(
              borderRadius: BorderRadius.circular(18),
              onTap: onTap,
              child: Container(
                decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(18),
                    boxShadow: const [BoxShadow(color: Color(0x52121417), blurRadius: 22, offset: Offset(0, 6))]),
                padding: const EdgeInsets.fromLTRB(14, 12, 12, 12),
                child: Row(children: [
                  Container(
                    width: 38,
                    height: 38,
                    decoration: BoxDecoration(color: C.ember, borderRadius: BorderRadius.circular(12)),
                    child: const Icon(Icons.warning_amber_rounded, color: Colors.white, size: 21),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                      Text(title,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 14.5, height: 1.3)),
                      if (body != null && body!.isNotEmpty) ...[
                        const SizedBox(height: 2),
                        Text(body!,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(color: Color(0xB3FFFFFF), fontSize: 13, height: 1.35)),
                      ],
                    ]),
                  ),
                  const SizedBox(width: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                    decoration: BoxDecoration(color: const Color(0x24FFFFFF), borderRadius: BorderRadius.circular(10)),
                    child: Text(action, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 13)),
                  ),
                ]),
              ),
            ),
          ),
        ),
      );
}

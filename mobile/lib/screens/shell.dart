import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app_state.dart';
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
      body: IndexedStack(index: _tab, children: _pages),
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

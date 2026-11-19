import 'package:flutter/material.dart';

import '../app_state.dart';
import '../reports_store.dart';
import '../strings.dart';
import '../theme.dart';
import '../widgets.dart';

/// Reports made on this phone, with their honest sync state (FR-OFF-005).
class MyReportsScreen extends StatelessWidget {
  const MyReportsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: ListenableBuilder(
          listenable: reportsStore,
          builder: (context, _) => FutureBuilder<List<LocalReport>>(
            future: reportsStore.all(),
            builder: (context, snap) {
              final items = snap.data ?? const <LocalReport>[];
              final waiting = items.where((r) => r.status == 'pending' || r.status == 'sending').length;
              return RefreshIndicator(
                onRefresh: reportsStore.sync,
                child: ListView(padding: const EdgeInsets.only(bottom: 24), children: [
                  PageHeader(tr(l, 'mine_title'), subtitle: tr(l, 'mine_sub')),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      if (snap.connectionState != ConnectionState.done && items.isEmpty)
                        const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))
                      else if (items.isEmpty)
                        EmptyState(icon: Icons.inbox_outlined, title: tr(l, 'no_mine_title'), body: tr(l, 'no_mine'))
                      else ...[
                        if (waiting > 0)
                          Container(
                            margin: const EdgeInsets.only(bottom: 12, top: 6),
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(color: C.amberTint, borderRadius: BorderRadius.circular(16)),
                            child: Row(children: [
                              const Icon(Icons.cloud_upload_outlined, color: C.amberText, size: 20),
                              const SizedBox(width: 10),
                              Expanded(child: Text(tr(l, 'waiting_to_send'), style: T.label.copyWith(color: C.amberText))),
                            ]),
                          ),
                        SCard(
                          padding: EdgeInsets.zero,
                          child: Column(children: [
                            for (var k = 0; k < items.length; k++) ...[
                              if (k > 0) const Divider(indent: 72),
                              _MineRow(r: items[k]),
                            ],
                          ]),
                        ),
                      ],
                    ]),
                  ),
                ]),
              );
            },
          ),
        ),
      ),
    );
  }
}

class _MineRow extends StatelessWidget {
  final LocalReport r;
  const _MineRow({required this.r});
  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final (label, fg, bg, icon) = switch (r.status) {
      'sent' => (tr(l, 'st_sent'), C.brandDeep, C.brandTint, Icons.check_rounded),
      'sending' => (tr(l, 'st_sending'), C.amberText, C.amberTint, Icons.sync_rounded),
      'needs_attention' => (tr(l, 'st_attention'), C.emberDeep, C.emberTint, Icons.priority_high_rounded),
      _ => (tr(l, 'st_pending'), C.amberText, C.amberTint, Icons.schedule_rounded),
    };
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        IconTile(categoryIcon(r.category), fg: C.ink, bg: C.paper, size: 44),
        const SizedBox(width: 14),
        Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(appState.categoryName(r.category), style: T.bodyStrong.copyWith(fontSize: 16)),
          const SizedBox(height: 2),
          Text([ago(r.createdAt, l), if (r.reference != null) r.reference!].join(' · '), style: T.caption),
          if (r.error != null && r.status == 'needs_attention')
            Padding(
                padding: const EdgeInsets.only(top: 4),
                child:
                    Text(r.error!, maxLines: 2, overflow: TextOverflow.ellipsis, style: T.caption.copyWith(color: C.emberDeep))),
        ])),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.fromLTRB(7, 4, 10, 4),
          decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(999)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 14, color: fg),
            const SizedBox(width: 4),
            Text(label, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: fg)),
          ]),
        ),
      ]),
    );
  }
}

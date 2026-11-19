import 'package:flutter/material.dart';

import '../app_state.dart';
import '../reports_store.dart';
import '../strings.dart';
import '../theme.dart';
import 'report_screen.dart';

/// After sending: says honestly whether it reached the server or is waiting on the phone, and
/// that sent does not mean confirmed (BR-23).
class SentScreen extends StatelessWidget {
  final LocalReport report;
  const SentScreen({super.key, required this.report});

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final sent = report.status == 'sent';
    final attention = report.status == 'needs_attention';
    final color = attention ? C.ember : (sent ? C.brand : C.amber);
    final steps = [
      (tr(l, 'step_saved'), true),
      (tr(l, 'step_sent'), sent),
      (tr(l, 'step_checked'), false),
    ];
    return Scaffold(
      backgroundColor: C.paper,
      appBar: AppBar(leading: IconButton(icon: const Icon(Icons.close_rounded), onPressed: () => Navigator.pop(context))),
      body: ListView(padding: const EdgeInsets.fromLTRB(24, 8, 24, 24), children: [
        TweenAnimationBuilder<double>(
          tween: Tween(begin: 0.6, end: 1),
          duration: const Duration(milliseconds: 420),
          curve: Curves.easeOutBack,
          builder: (_, v, child) => Transform.scale(scale: v, alignment: Alignment.centerLeft, child: child),
          child: Align(
              alignment: Alignment.centerLeft,
              child: Container(
                width: 72,
                height: 72,
                decoration: BoxDecoration(
                    color: color,
                    shape: BoxShape.circle,
                    boxShadow: [BoxShadow(color: color.withValues(alpha: .35), blurRadius: 20, offset: const Offset(0, 8))]),
                child: Icon(sent ? Icons.check_rounded : (attention ? Icons.priority_high_rounded : Icons.cloud_off_rounded),
                    color: Colors.white, size: 36),
              )),
        ),
        const SizedBox(height: 22),
        Text(attention ? tr(l, 'st_attention') : tr(l, sent ? 'sent_title' : 'saved_title'),
            style: T.title.copyWith(fontSize: 30)),
        const SizedBox(height: 10),
        Text(attention ? (report.error ?? tr(l, 'error_generic')) : tr(l, sent ? 'sent_body' : 'saved_body'),
            style: T.body.copyWith(fontSize: 16)),
        const SizedBox(height: 26),
        if (!attention)
          Container(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
            decoration:
                BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20), border: Border.all(color: C.line)),
            child: Column(children: [
              for (var k = 0; k < steps.length; k++)
                Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: Row(children: [
                    Container(
                        width: 24,
                        height: 24,
                        decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: steps[k].$2 ? C.ink : Colors.white,
                            border: Border.all(color: steps[k].$2 ? C.ink : C.line2, width: 1.5)),
                        child: steps[k].$2 ? const Icon(Icons.check_rounded, size: 15, color: Colors.white) : null),
                    const SizedBox(width: 12),
                    Expanded(
                        child: Text(steps[k].$1,
                            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: steps[k].$2 ? C.ink : C.ink3))),
                  ]),
                ),
            ]),
          ),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(color: C.brandWash, borderRadius: BorderRadius.circular(20)),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Icon(Icons.visibility_off_rounded, color: C.brand, size: 20),
            const SizedBox(width: 12),
            Expanded(
                child: Text(tr(l, 'sent_private') + (report.reference != null ? ' (${report.reference}).' : '.'),
                    style: T.body.copyWith(fontSize: 14, color: C.ink))),
          ]),
        ),
      ]),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 10),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            SizedBox(
                width: double.infinity,
                child: FilledButton(onPressed: () => Navigator.pop(context), child: Text(tr(l, 'back_to_map')))),
            const SizedBox(height: 4),
            TextButton(
              onPressed: () => Navigator.of(context)
                  .pushReplacement(MaterialPageRoute(builder: (_) => const ReportScreen(), fullscreenDialog: true)),
              child: Text(tr(l, 'report_another')),
            ),
          ]),
        ),
      ),
    );
  }
}

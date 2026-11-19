import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../app_state.dart';
import '../strings.dart';
import '../theme.dart';
import '../widgets.dart';

class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final l = appState.lang;
    final points = [
      (Icons.bolt_rounded, tr(l, 'promise_report')),
      (Icons.route_rounded, tr(l, 'promise_map')),
      (Icons.visibility_off_rounded, tr(l, 'promise_private')),
    ];
    return Scaffold(
      backgroundColor: C.paper,
      body: SafeArea(
        child: LayoutBuilder(
            builder: (context, c) => SingleChildScrollView(
                  child: ConstrainedBox(
                    constraints: BoxConstraints(minHeight: c.maxHeight),
                    child: IntrinsicHeight(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                        Padding(
                          padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
                          child: Row(children: [
                            const SisayMark(size: 30),
                            const SizedBox(width: 10),
                            const Text('Sisay',
                                style: TextStyle(
                                    fontFamily: 'Manrope', fontSize: 20, fontWeight: FontWeight.w800, letterSpacing: -0.5)),
                            const Spacer(),
                            _LangToggle(lang: l),
                          ]),
                        ),
                        const SizedBox(height: 16),
                        const Padding(
                            padding: EdgeInsets.symmetric(horizontal: 16),
                            child: AspectRatio(aspectRatio: 1.25, child: _HeroMap())),
                        Padding(
                          padding: const EdgeInsets.fromLTRB(24, 24, 24, 0),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text(tr(l, 'tagline'), style: T.display),
                            const SizedBox(height: 10),
                            Text(tr(l, 'welcome_sub'), style: T.body.copyWith(fontSize: 16.5)),
                            const SizedBox(height: 20),
                            for (final p in points)
                              Padding(
                                padding: const EdgeInsets.only(bottom: 12),
                                child: Row(children: [
                                  Icon(p.$1, size: 20, color: C.brand),
                                  const SizedBox(width: 12),
                                  Expanded(
                                      child: Text(p.$2,
                                          style: const TextStyle(
                                              fontSize: 15, fontWeight: FontWeight.w500, color: C.ink, height: 1.35))),
                                ]),
                              ),
                          ]),
                        ),
                        const Spacer(),
                        Padding(
                          padding: const EdgeInsets.fromLTRB(20, 16, 20, 16),
                          child: Column(children: [
                            FilledButton(
                                onPressed: appState.finishOnboarding,
                                child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                                  Text(tr(l, 'get_started')),
                                  const SizedBox(width: 8),
                                  const Icon(Icons.arrow_forward_rounded, size: 20),
                                ])),
                            const SizedBox(height: 10),
                            Text(tr(l, 'no_account_needed'), style: T.caption),
                          ]),
                        ),
                      ]),
                    ),
                  ),
                )),
      ),
    );
  }
}

class _LangToggle extends StatelessWidget {
  final String lang;
  const _LangToggle({required this.lang});
  @override
  Widget build(BuildContext context) => SizedBox(
        width: 120,
        child: Segmented<String>(options: const [('en', 'EN'), ('fr', 'FR')], value: lang, onChanged: appState.setLang),
      );
}

/// A drawn, stylised map: roads, a river, a few reports and an alert on a route. It explains the
/// product before any words do, and it never shows a real place's real data.
class _HeroMap extends StatelessWidget {
  const _HeroMap();
  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(28),
        child: LayoutBuilder(builder: (context, c) {
          final w = c.maxWidth, h = c.maxHeight;
          Widget at(double x, double y, Widget child, {double size = 0}) =>
              Positioned(left: x * w - size / 2, top: y * h - size / 2, child: child);
          return Stack(children: [
            Positioned.fill(child: CustomPaint(painter: FakeMapPainter(routeHighlight: true))),
            at(.26, .50, const IncidentPin(category: 'road_blockage', verification: 'verified', size: 38), size: 38 * 1.2),
            at(.86, .40, const IncidentPin(category: 'fire', lifecycle: 'resolved', size: 34), size: 34 * 1.2),
            at(.62, .68, const IncidentPin(category: 'shooting', size: 40, fresh: true), size: 80),
            at(.18, .86, const LocationDot(), size: 40),
            Positioned(
              left: 14,
              right: 14,
              top: 14,
              child: Container(
                padding: const EdgeInsets.fromLTRB(12, 10, 14, 10),
                decoration: BoxDecoration(
                    color: C.ember,
                    borderRadius: BorderRadius.circular(16),
                    boxShadow: const [BoxShadow(color: Color(0x33121417), blurRadius: 14, offset: Offset(0, 4))]),
                child: Row(children: [
                  const Icon(Icons.warning_amber_rounded, color: Colors.white, size: 20),
                  const SizedBox(width: 10),
                  Expanded(
                      child: Text(appState.lang == 'fr' ? 'Tirs signalés sur votre trajet' : 'Shooting reported on your route',
                          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 14))),
                  Text(appState.lang == 'fr' ? '2 min' : '2 min ago',
                      style: const TextStyle(color: Color(0xD9FFFFFF), fontSize: 12.5, fontWeight: FontWeight.w500)),
                ]),
              ),
            ),
          ]);
        }),
      );
}

/// Painted stand-in for a basemap (also used by screenshot tests).
class FakeMapPainter extends CustomPainter {
  final bool routeHighlight;
  FakeMapPainter({this.routeHighlight = false});

  @override
  void paint(Canvas canvas, Size s) {
    final w = s.width, h = s.height;
    canvas.drawRect(Offset.zero & s, Paint()..color = const Color(0xFFF2EFE9));
    // blocks of green
    final park = Paint()..color = const Color(0xFFDDEBD5);
    canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(w * .62, h * .05, w * .34, h * .22), const Radius.circular(14)), park);
    canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(w * .03, h * .42, w * .2, h * .2), const Radius.circular(14)), park);
    // river
    final river = Path()
      ..moveTo(0, h * .95)
      ..cubicTo(w * .3, h * .82, w * .45, h * 1.0, w * .75, h * .86)
      ..cubicTo(w * .88, h * .8, w * .95, h * .84, w, h * .8);
    canvas.drawPath(
        river,
        Paint()
          ..color = const Color(0xFFBFD9EE)
          ..style = PaintingStyle.stroke
          ..strokeWidth = h * .05
          ..strokeCap = StrokeCap.round);
    // minor streets
    final minor = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.stroke
      ..strokeWidth = 5
      ..strokeCap = StrokeCap.round;
    final rnd = math.Random(7);
    for (var i = 0; i < 9; i++) {
      final y = h * (.08 + i * .11) + rnd.nextDouble() * 8;
      canvas.drawLine(Offset(-10, y), Offset(w + 10, y + (rnd.nextDouble() - .5) * h * .18), minor);
    }
    for (var i = 0; i < 7; i++) {
      final x = w * (.05 + i * .15) + rnd.nextDouble() * 10;
      canvas.drawLine(Offset(x, -10), Offset(x + (rnd.nextDouble() - .5) * w * .2, h + 10), minor);
    }
    // main road
    final main = Path()
      ..moveTo(w * .1, h * 1.05)
      ..cubicTo(w * .25, h * .7, w * .45, h * .72, w * .58, h * .55)
      ..cubicTo(w * .7, h * .4, w * .8, h * .3, w * 1.05, h * .18);
    canvas.drawPath(
        main,
        Paint()
          ..color = const Color(0xFFF7D9A6)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 14
          ..strokeCap = StrokeCap.round);
    canvas.drawPath(
        main,
        Paint()
          ..color = const Color(0xFFFCE7C2)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 10
          ..strokeCap = StrokeCap.round);
    if (routeHighlight) {
      canvas.drawPath(
          main,
          Paint()
            ..color = C.brand.withValues(alpha: .85)
            ..style = PaintingStyle.stroke
            ..strokeWidth = 5
            ..strokeCap = StrokeCap.round);
    }
  }

  @override
  bool shouldRepaint(FakeMapPainter old) => old.routeHighlight != routeHighlight;
}

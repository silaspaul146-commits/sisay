import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'theme.dart';

IconData categoryIcon(String code) => switch (code) {
      'shooting' => Icons.gps_fixed_rounded,
      'armed_clash' => Icons.warning_amber_rounded,
      'road_blockage' => Icons.remove_road_rounded,
      'fire' => Icons.local_fire_department_rounded,
      'road_accident' => Icons.car_crash_rounded,
      'flood' => Icons.flood_rounded,
      'kidnapping' => Icons.person_off_rounded,
      'missing_person' => Icons.person_search_rounded,
      'medical_emergency' => Icons.medical_services_rounded,
      'explosion' => Icons.flare_rounded,
      'building_collapse' => Icons.domain_disabled_rounded,
      'landslide' => Icons.landslide_rounded,
      'infrastructure_emergency' => Icons.power_off_rounded,
      'displacement' => Icons.directions_walk_rounded,
      'more' => Icons.grid_view_rounded,
      _ => Icons.more_horiz_rounded,
    };

/// Small status pill. A leading glyph carries the meaning for people who can't tell the colours apart.
class StatusChip extends StatelessWidget {
  final Status status;
  final bool onDark;
  const StatusChip(this.status, {super.key, this.onDark = false});
  @override
  Widget build(BuildContext context) {
    final fg = onDark ? Colors.white : status.fg;
    return Container(
      padding: const EdgeInsets.fromLTRB(8, 4, 10, 4),
      decoration: BoxDecoration(
        color: onDark ? Colors.white.withValues(alpha: .18) : status.bg,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        _StatusGlyph(status: status, color: fg),
        const SizedBox(width: 6),
        Text(status.label, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: fg, height: 1.2)),
      ]),
    );
  }
}

class _StatusGlyph extends StatelessWidget {
  final Status status;
  final Color color;
  const _StatusGlyph({required this.status, required this.color});
  @override
  Widget build(BuildContext context) => SizedBox(
        width: 9,
        height: 9,
        child: status.dashed
            ? CustomPaint(painter: _DashedRing(color, stroke: 1.6, dashes: 6))
            : DecoratedBox(
                decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: status.solid ? color : Colors.transparent,
                    border: status.solid ? null : Border.all(color: color, width: 1.8))),
      );
}

/// Map pin: ring = people say so, solid = our team checked, dashed = someone disagrees, grey = over.
class IncidentPin extends StatelessWidget {
  final String category;
  final String? verification;
  final String? lifecycle;
  final double size;
  final bool fresh;
  const IncidentPin({super.key, required this.category, this.verification, this.lifecycle, this.size = 40, this.fresh = false});

  @override
  Widget build(BuildContext context) {
    final over = lifecycle == 'resolved' || lifecycle == 'closed';
    final verified = verification == 'verified';
    final disputed = verification == 'disputed';
    final ring = over ? C.grey : (disputed ? C.rose : C.amber);
    final fill = over ? C.greyTint : (verified ? C.brand : Colors.white);
    final iconColor = over ? C.ink3 : (verified ? Colors.white : ring);
    final pin = Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: fill,
        shape: BoxShape.circle,
        border:
            (disputed || verified) ? Border.all(color: Colors.white, width: 2.5) : Border.all(color: ring, width: size * .075),
        boxShadow: const [
          BoxShadow(color: Color(0x2E121417), blurRadius: 10, offset: Offset(0, 4)),
          BoxShadow(color: Color(0x14121417), blurRadius: 2, offset: Offset(0, 1)),
        ],
      ),
      child: CustomPaint(
        painter: disputed ? _DashedRing(ring, stroke: size * .075) : null,
        child: Icon(categoryIcon(category), size: size * .5, color: iconColor),
      ),
    );
    final badge = verified && !over
        ? Positioned(
            right: -3,
            top: -3,
            child: Container(
                width: size * .4,
                height: size * .4,
                decoration: BoxDecoration(
                    color: Colors.white,
                    shape: BoxShape.circle,
                    boxShadow: const [BoxShadow(color: Color(0x22121417), blurRadius: 3)]),
                child: Icon(Icons.check_rounded, size: size * .3, color: C.brand)))
        : verification == 'under_review' && !over
            ? Positioned(
                right: -1,
                top: -1,
                child: Container(
                    width: size * .32,
                    height: size * .32,
                    decoration:
                        BoxDecoration(color: C.amber, shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 2))))
            : null;
    return SizedBox(
      width: size * (fresh ? 2 : 1.2),
      height: size * (fresh ? 2 : 1.2),
      child: Stack(alignment: Alignment.center, clipBehavior: Clip.none, children: [
        if (fresh) _Ripple(size: size * 2, color: verified ? C.brand : C.ember),
        Stack(clipBehavior: Clip.none, children: [pin, if (badge != null) badge]),
      ]),
    );
  }
}

/// Soft pulse behind reports from the last half hour.
class _Ripple extends StatefulWidget {
  final double size;
  final Color color;
  const _Ripple({required this.size, required this.color});
  @override
  State<_Ripple> createState() => _RippleState();
}

class _RippleState extends State<_Ripple> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2200))..repeat();
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (_, __) {
          final t = Curves.easeOut.transform(_c.value);
          return Container(
            width: widget.size * (.55 + .45 * t),
            height: widget.size * (.55 + .45 * t),
            decoration: BoxDecoration(shape: BoxShape.circle, color: widget.color.withValues(alpha: .22 * (1 - t))),
          );
        },
      );
}

class _DashedRing extends CustomPainter {
  final Color color;
  final double stroke;
  final int dashes;
  _DashedRing(this.color, {this.stroke = 3, this.dashes = 12});
  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.round;
    final r = size.width / 2 - stroke / 2;
    for (var i = 0; i < dashes; i++) {
      final a = i * 2 * math.pi / dashes;
      canvas.drawArc(Rect.fromCircle(center: size.center(Offset.zero), radius: r), a, math.pi / dashes, false, p);
    }
  }

  @override
  bool shouldRepaint(_DashedRing old) => old.color != color || old.stroke != stroke;
}

/// "Me" on the map: a blue dot with a soft halo.
class LocationDot extends StatelessWidget {
  const LocationDot({super.key});
  @override
  Widget build(BuildContext context) => Container(
        width: 40,
        height: 40,
        alignment: Alignment.center,
        decoration: BoxDecoration(shape: BoxShape.circle, color: C.location.withValues(alpha: .16)),
        child: Container(
            width: 18,
            height: 18,
            decoration: BoxDecoration(
              color: C.location,
              shape: BoxShape.circle,
              border: Border.all(color: Colors.white, width: 3),
              boxShadow: const [BoxShadow(color: Color(0x40121417), blurRadius: 5, offset: Offset(0, 1))],
            )),
      );
}

class SectionLabel extends StatelessWidget {
  final String text;
  final Widget? trailing;
  const SectionLabel(this.text, {super.key, this.trailing});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 22, 4, 8),
        child: Row(children: [
          Expanded(child: Text(text.toUpperCase(), style: T.overline)),
          if (trailing != null) trailing!,
        ]),
      );
}

/// Large page heading used by every tab, so they read as one product.
class PageHeader extends StatelessWidget {
  final String title;
  final String? subtitle;
  final Widget? action;
  const PageHeader(this.title, {super.key, this.subtitle, this.action});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 12, 4),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: T.title),
            if (subtitle != null) ...[
              const SizedBox(height: 6),
              Text(subtitle!, style: T.body.copyWith(fontSize: 14.5)),
            ],
          ])),
          if (action != null) action!,
        ]),
      );
}

/// White card on paper, hairline border, no heavy shadow.
class SCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;
  final Color color;
  const SCard({super.key, required this.child, this.padding = const EdgeInsets.all(16), this.onTap, this.color = C.surface});
  @override
  Widget build(BuildContext context) => Material(
        color: color,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20), side: const BorderSide(color: C.line)),
        clipBehavior: Clip.antiAlias,
        child: InkWell(onTap: onTap, child: Padding(padding: padding, child: child)),
      );
}

/// Rounded-square icon tile.
class IconTile extends StatelessWidget {
  final IconData icon;
  final Color fg, bg;
  final double size;
  const IconTile(this.icon, {super.key, this.fg = C.brand, this.bg = C.brandTint, this.size = 44});
  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(size * .32)),
        child: Icon(icon, color: fg, size: size * .5),
      );
}

/// Round icon button that floats over the map.
class MapButton extends StatelessWidget {
  final IconData icon;
  final VoidCallback onTap;
  final String tooltip;
  final Color color;
  const MapButton({super.key, required this.icon, required this.onTap, required this.tooltip, this.color = C.ink});
  @override
  Widget build(BuildContext context) => Tooltip(
        message: tooltip,
        child: Material(
          color: Colors.white,
          shape: const CircleBorder(),
          elevation: 0,
          child: Ink(
            decoration: const BoxDecoration(shape: BoxShape.circle, boxShadow: [
              BoxShadow(color: Color(0x24121417), blurRadius: 12, offset: Offset(0, 3)),
            ]),
            child: InkWell(
                customBorder: const CircleBorder(),
                onTap: onTap,
                child: SizedBox(width: 46, height: 46, child: Icon(icon, color: color, size: 22))),
          ),
        ),
      );
}

/// iOS-style segmented control, drawn by hand so it doesn't look like stock Material.
class Segmented<T> extends StatelessWidget {
  final List<(T, String)> options;
  final T value;
  final ValueChanged<T> onChanged;
  const Segmented({super.key, required this.options, required this.value, required this.onChanged});
  @override
  Widget build(BuildContext context) {
    final index = options.indexWhere((o) => o.$1 == value);
    return Container(
      height: 44,
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(color: C.sunk, borderRadius: BorderRadius.circular(14)),
      child: LayoutBuilder(builder: (context, c) {
        final w = c.maxWidth / options.length;
        return Stack(children: [
          AnimatedPositioned(
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOutCubic,
            left: w * index,
            top: 0,
            bottom: 0,
            width: w,
            child: Container(
                decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(10),
                    boxShadow: const [BoxShadow(color: Color(0x1F121417), blurRadius: 6, offset: Offset(0, 2))])),
          ),
          Row(children: [
            for (final o in options)
              Expanded(
                  child: Semantics(
                button: true,
                selected: o.$1 == value,
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => onChanged(o.$1),
                  child: Center(
                      child: Text(o.$2,
                          style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: o.$1 == value ? C.ink : C.ink2))),
                ),
              )),
          ]),
        ]);
      }),
    );
  }
}

/// Single-choice chips (e.g. alert distance).
class ChoiceRow<T> extends StatelessWidget {
  final List<(T, String)> options;
  final T value;
  final ValueChanged<T> onChanged;
  const ChoiceRow({super.key, required this.options, required this.value, required this.onChanged});
  @override
  Widget build(BuildContext context) => Wrap(spacing: 8, runSpacing: 8, children: [
        for (final o in options)
          Semantics(
            button: true,
            selected: o.$1 == value,
            child: GestureDetector(
              onTap: () => onChanged(o.$1),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 160),
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                decoration: BoxDecoration(
                  color: o.$1 == value ? C.ink : Colors.white,
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(color: o.$1 == value ? C.ink : C.line2),
                ),
                child: Text(o.$2,
                    style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: o.$1 == value ? Colors.white : C.ink)),
              ),
            ),
          ),
      ]);
}

/// Calm empty state with a drawn mark instead of a stock icon.
class EmptyState extends StatelessWidget {
  final IconData icon;
  final String title, body;
  final Widget? action;
  const EmptyState({super.key, required this.icon, required this.title, required this.body, this.action});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(28, 36, 28, 24),
        child: Column(children: [
          Container(
            width: 88,
            height: 88,
            decoration: const BoxDecoration(color: C.brandWash, shape: BoxShape.circle),
            child: Center(
                child: Container(
                    width: 56,
                    height: 56,
                    decoration: const BoxDecoration(color: C.brandTint, shape: BoxShape.circle),
                    child: Icon(icon, color: C.brand, size: 28))),
          ),
          const SizedBox(height: 18),
          Text(title, textAlign: TextAlign.center, style: T.headline),
          const SizedBox(height: 6),
          Text(body, textAlign: TextAlign.center, style: T.body),
          if (action != null) ...[const SizedBox(height: 20), action!],
        ]),
      );
}

/// Sisay mark: an eye-like ring with a speaking dot. See it, say it.
class SisayMark extends StatelessWidget {
  final double size;
  final Color color;
  const SisayMark({super.key, this.size = 32, this.color = C.brand});
  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(size * .3)),
        child: CustomPaint(painter: _MarkPainter()),
      );
}

class _MarkPainter extends CustomPainter {
  // A speech bubble with an eye in it: see it, say it.
  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final bubble = RRect.fromRectAndRadius(Rect.fromLTWH(w * .2, w * .2, w * .6, w * .5), Radius.circular(w * .2));
    final tail = Path()
      ..moveTo(w * .32, w * .62)
      ..lineTo(w * .27, w * .82)
      ..lineTo(w * .48, w * .68)
      ..close();
    final white = Paint()..color = Colors.white;
    canvas.drawRRect(bubble, white);
    canvas.drawPath(tail, white);
    canvas.drawCircle(Offset(w * .5, w * .45), w * .135, Paint()..color = C.brand);
    canvas.drawCircle(Offset(w * .54, w * .41), w * .04, white);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

String ago(DateTime t, String lang) {
  final d = DateTime.now().difference(t.toLocal());
  final fr = lang == 'fr';
  if (d.inMinutes < 1) return fr ? "à l'instant" : 'just now';
  if (d.inMinutes < 60) return fr ? 'il y a ${d.inMinutes} min' : '${d.inMinutes} min ago';
  if (d.inHours < 48) return fr ? 'il y a ${d.inHours} h' : '${d.inHours} h ago';
  return fr ? 'il y a ${d.inDays} j' : '${d.inDays} days ago';
}

String distance(double meters) =>
    meters < 1000 ? '${(meters / 50).round() * 50} m' : '${(meters / 1000).toStringAsFixed(meters < 10000 ? 1 : 0)} km';

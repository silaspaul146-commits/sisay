import 'package:flutter/material.dart';

/// Sisay design tokens, v2.
///
/// Warm paper and ink for calm; one indigo for "Sisay" (actions you take, things our team
/// confirmed); ember only when something needs your attention right now. Status is always shape
/// plus word, never colour alone.
class C {
  // neutrals
  static const paper = Color(0xFFF4F2EE);
  static const surface = Colors.white;
  static const sunk = Color(0xFFECE9E3);
  static const ink = Color(0xFF121417);
  static const ink2 = Color(0xFF4A4F59);
  static const ink3 = Color(0xFF767C87);
  static const line = Color(0xFFE8E5DF);
  static const line2 = Color(0xFFD7D3CB);

  // brand
  static const brand = Color(0xFF3A40C4);
  static const brandDeep = Color(0xFF272B8A);
  static const brandTint = Color(0xFFE7E8FA);
  static const brandWash = Color(0xFFF1F1FC);

  // attention
  static const ember = Color(0xFFD9481C);
  static const emberDeep = Color(0xFFA8350F);
  static const emberTint = Color(0xFFFCEDE6);

  // status
  static const amber = Color(0xFFB7791F);
  static const amberText = Color(0xFF7A4E0A);
  static const amberTint = Color(0xFFFBF1DC);
  static const rose = Color(0xFFB4367A);
  static const roseTint = Color(0xFFF8E6EF);
  static const grey = Color(0xFF9EA3AB);
  static const greyTint = Color(0xFFECEBE8);
  static const location = Color(0xFF1E88E5);

  // Back-compat names used across screens.
  static const harbour = brand;
  static const harbourDeep = brandDeep;
  static const harbourTint = brandTint;
  static const harbourWash = brandWash;
  static const mist = paper;
  static const signal = ember;
  static const signalTint = emberTint;
  static const purple = rose;
  static const purpleTint = roseTint;
}

/// Type scale. Manrope for headings (warm, a little character); Inter for reading.
class T {
  static const _m = 'Manrope';
  static const display =
      TextStyle(fontFamily: _m, fontSize: 34, fontWeight: FontWeight.w800, height: 1.08, letterSpacing: -1.0, color: C.ink);
  static const title =
      TextStyle(fontFamily: _m, fontSize: 26, fontWeight: FontWeight.w800, height: 1.15, letterSpacing: -0.6, color: C.ink);
  static const headline =
      TextStyle(fontFamily: _m, fontSize: 19, fontWeight: FontWeight.w700, height: 1.25, letterSpacing: -0.3, color: C.ink);
  static const subhead =
      TextStyle(fontFamily: _m, fontSize: 16, fontWeight: FontWeight.w700, height: 1.3, letterSpacing: -0.1, color: C.ink);
  static const body = TextStyle(fontSize: 15, height: 1.5, color: C.ink2);
  static const bodyStrong = TextStyle(fontSize: 15, height: 1.4, fontWeight: FontWeight.w600, color: C.ink);
  static const label = TextStyle(fontSize: 13, height: 1.3, fontWeight: FontWeight.w600, color: C.ink);
  static const caption = TextStyle(fontSize: 13, height: 1.35, fontWeight: FontWeight.w500, color: C.ink3);
  static const overline = TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, letterSpacing: 0.9, color: C.ink3);
}

ThemeData sisayTheme() {
  final scheme = ColorScheme.fromSeed(seedColor: C.brand, primary: C.brand, surface: C.surface)
      .copyWith(onSurface: C.ink, onSurfaceVariant: C.ink2, outline: C.line2, outlineVariant: C.line);
  final base = ThemeData(useMaterial3: true, colorScheme: scheme, fontFamily: 'Inter', scaffoldBackgroundColor: C.paper);
  final r14 = BorderRadius.circular(14);
  return base.copyWith(
    textTheme: base.textTheme.apply(bodyColor: C.ink, displayColor: C.ink),
    splashFactory: InkSparkle.splashFactory,
    appBarTheme: const AppBarTheme(
      backgroundColor: C.paper,
      foregroundColor: C.ink,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle:
          TextStyle(fontFamily: 'Manrope', fontSize: 18, fontWeight: FontWeight.w700, color: C.ink, letterSpacing: -0.2),
    ),
    filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
      backgroundColor: C.ink,
      foregroundColor: Colors.white,
      disabledBackgroundColor: C.sunk,
      disabledForegroundColor: C.ink3,
      minimumSize: const Size.fromHeight(56),
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      textStyle: const TextStyle(fontFamily: 'Manrope', fontSize: 16, fontWeight: FontWeight.w700, letterSpacing: -0.1),
    )),
    outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
      foregroundColor: C.ink,
      minimumSize: const Size.fromHeight(52),
      side: const BorderSide(color: C.line2),
      backgroundColor: C.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      textStyle: const TextStyle(fontFamily: 'Manrope', fontSize: 15, fontWeight: FontWeight.w700),
    )),
    textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
      foregroundColor: C.brand,
      minimumSize: const Size(48, 44),
      textStyle: const TextStyle(fontFamily: 'Inter', fontSize: 14.5, fontWeight: FontWeight.w600),
    )),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: C.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      hintStyle: const TextStyle(color: C.ink3, fontSize: 15),
      labelStyle: const TextStyle(color: C.ink2),
      floatingLabelStyle: const TextStyle(color: C.brand, fontWeight: FontWeight.w600),
      counterStyle: const TextStyle(color: C.ink3, fontSize: 12),
      border: OutlineInputBorder(borderRadius: r14, borderSide: const BorderSide(color: C.line2)),
      enabledBorder: OutlineInputBorder(borderRadius: r14, borderSide: const BorderSide(color: C.line2)),
      focusedBorder: OutlineInputBorder(borderRadius: r14, borderSide: const BorderSide(color: C.brand, width: 1.6)),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: const WidgetStatePropertyAll(Colors.white),
      trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? C.brand : C.line2),
      trackOutlineColor: const WidgetStatePropertyAll(Colors.transparent),
      thumbIcon: const WidgetStatePropertyAll(null),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: C.ink,
      elevation: 0,
      contentTextStyle: const TextStyle(fontFamily: 'Inter', color: Colors.white, fontSize: 14.5, fontWeight: FontWeight.w500),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: C.surface,
      surfaceTintColor: Colors.transparent,
      showDragHandle: true,
      dragHandleColor: C.line2,
      dragHandleSize: Size(36, 4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28))),
    ),
    dialogTheme: DialogTheme(
        backgroundColor: C.surface,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24))),
    progressIndicatorTheme: const ProgressIndicatorThemeData(color: C.brand),
    dividerTheme: const DividerThemeData(color: C.line, thickness: 1, space: 1),
    pageTransitionsTheme: const PageTransitionsTheme(builders: {
      TargetPlatform.android: ZoomPageTransitionsBuilder(),
    }),
  );
}

/// Status vocabulary shared by pins, chips and lists.
class Status {
  final String label;
  final Color fg;
  final Color bg;
  final bool solid;
  final bool dashed;
  const Status(this.label, this.fg, this.bg, {this.solid = false, this.dashed = false});
}

Status statusOf(String? verification, String? lifecycle, String lang) {
  final fr = lang == 'fr';
  if (lifecycle == 'resolved' || lifecycle == 'closed') return Status(fr ? 'Terminé' : 'Over', C.ink2, C.greyTint, solid: true);
  switch (verification) {
    case 'verified':
      return Status(fr ? 'Vérifié' : 'Verified', C.brandDeep, C.brandTint, solid: true);
    case 'disputed':
      return Status(fr ? 'Contesté' : 'Disputed', const Color(0xFF8A2459), C.roseTint, dashed: true);
    case 'under_review':
      return Status(fr ? 'En vérification' : 'Being checked', C.amberText, C.amberTint);
    default:
      return Status(fr ? 'Non confirmé' : 'Unconfirmed', C.amberText, C.amberTint);
  }
}

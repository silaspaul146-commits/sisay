import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sisay/strings.dart';
import 'package:sisay/theme.dart';
import 'package:sisay/widgets.dart';

void main() {
  test('every English string has a French translation and nothing says "safe" as a promise', () {
    for (final key in ['tagline', 'no_reports_body', 'send', 'saved_body', 'places_sub']) {
      expect(tr('fr', key), isNot(equals(tr('en', key))), reason: key);
    }
    expect(tr('en', 'no_reports_body'), contains("doesn't mean it's safe"));
  });

  test('every string has French copy', () {
    expect(missingFrench(), isEmpty);
  });

  test('status vocabulary', () {
    expect(statusOf('verified', 'active', 'en').label, 'Verified');
    expect(statusOf('unverified', 'active', 'fr').label, 'Non confirmé');
    expect(statusOf('verified', 'resolved', 'en').label, 'Over');
  });

  testWidgets('pins render for every status', (tester) async {
    await tester.pumpWidget(const MaterialApp(
        home: Row(children: [
      IncidentPin(category: 'shooting'),
      IncidentPin(category: 'fire', verification: 'verified'),
      IncidentPin(category: 'flood', verification: 'disputed'),
      IncidentPin(category: 'fire', lifecycle: 'resolved'),
    ])));
    expect(find.byType(IncidentPin), findsNWidgets(4));
  });
}

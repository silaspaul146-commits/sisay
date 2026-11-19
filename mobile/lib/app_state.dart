import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';

class Category {
  final String code, name;
  const Category(this.code, this.name);
}

/// Built-in list so reporting works offline on first launch; refreshed from the server.
const fallbackCategories = [
  Category('shooting', 'Shooting'),
  Category('armed_clash', 'Armed clash'),
  Category('road_blockage', 'Road blockage'),
  Category('fire', 'Fire'),
  Category('road_accident', 'Road accident'),
  Category('flood', 'Flood'),
  Category('kidnapping', 'Kidnapping'),
  Category('medical_emergency', 'Medical emergency'),
  Category('missing_person', 'Missing person'),
  Category('explosion', 'Explosion'),
  Category('building_collapse', 'Building collapse'),
  Category('landslide', 'Landslide'),
  Category('infrastructure_emergency', 'Infrastructure emergency'),
  Category('displacement', 'Displacement'),
  Category('other', 'Other'),
];

const _frNames = {
  'shooting': 'Tirs',
  'armed_clash': 'Affrontement armé',
  'road_blockage': 'Route bloquée',
  'fire': 'Incendie',
  'road_accident': 'Accident',
  'flood': 'Inondation',
  'kidnapping': 'Enlèvement',
  'medical_emergency': 'Urgence médicale',
  'missing_person': 'Personne disparue',
  'explosion': 'Explosion',
  'building_collapse': 'Effondrement',
  'landslide': 'Glissement de terrain',
  'infrastructure_emergency': 'Panne (eau, électricité)',
  'displacement': 'Déplacement de population',
  'other': 'Autre',
};

class AppState extends ChangeNotifier {
  late SharedPreferences _prefs;
  String lang = 'en';
  bool onboarded = false;
  List<Category> categories = fallbackCategories;

  Future<void> load() async {
    _prefs = await SharedPreferences.getInstance();
    lang = _prefs.getString('lang') ?? 'en';
    onboarded = _prefs.getBool('onboarded') ?? false;
    refreshCategories();
  }

  Future<void> refreshCategories() async {
    try {
      final r = await api.send('GET', '/incident-categories');
      final items = (r['items'] as List).map((c) => Category(c['code'] as String, c['name'] as String)).toList();
      if (items.isNotEmpty) {
        categories = items;
        notifyListeners();
      }
    } on ApiException {
      // offline: keep the built-in list
    }
  }

  String categoryName(String code) {
    if (lang == 'fr' && _frNames.containsKey(code)) return _frNames[code]!;
    for (final c in categories) {
      if (c.code == code) return c.name;
    }
    return code.replaceAll('_', ' ');
  }

  Future<void> setLang(String l) async {
    lang = l;
    await _prefs.setString('lang', l);
    notifyListeners();
  }

  Future<void> finishOnboarding() async {
    onboarded = true;
    await _prefs.setBool('onboarded', true);
    notifyListeners();
  }
}

final appState = AppState();

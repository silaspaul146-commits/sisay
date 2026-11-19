import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'app_state.dart';
import 'identity.dart';
import 'reports_store.dart';
import 'screens/shell.dart';
import 'screens/welcome.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.dark,
    systemNavigationBarColor: Colors.white,
    systemNavigationBarIconBrightness: Brightness.dark,
  ));
  await appState.load();
  await identity.load();
  await reportsStore.open(); // the offline queue must be ready before anyone can report
  identity.ensureRegistered(); // best effort; retried by the queue's sync
  runApp(const SisayApp());
}

class SisayApp extends StatelessWidget {
  const SisayApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: appState,
      builder: (context, _) => MaterialApp(
        title: 'Sisay',
        debugShowCheckedModeBanner: false,
        theme: sisayTheme(),
        home: appState.onboarded ? const Shell() : const WelcomeScreen(),
      ),
    );
  }
}

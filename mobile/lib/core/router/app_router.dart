import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/analytics/analytics_screen.dart';
import '../../features/auth/application/auth_controller.dart';
import '../../features/auth/presentation/forgot_password_screen.dart';
import '../../features/auth/presentation/login_screen.dart';
import '../../features/auth/presentation/sign_up_screen.dart';
import '../../features/chat/presentation/chat_screen.dart';
import '../../features/home/presentation/home_screen.dart';
import '../../features/notifications/notifications_screen.dart';
import '../../features/profile/presentation/profile_screens.dart';
import '../../features/risk/domain/cdc_risk.dart';
import '../../features/risk/presentation/risk_screens.dart';
import '../../features/tracking/presentation/exercise_water_screens.dart';
import '../../features/tracking/presentation/glucose_screens.dart';
import '../../features/tracking/presentation/meal_screens.dart';
import '../../features/tracking/presentation/medication_screens.dart';
import '../../features/tracking/presentation/tracking_hub_screen.dart';
import '../widgets/main_shell.dart';
import 'routes.dart';

final _rootKey = GlobalKey<NavigatorState>();

/// Full-screen route pushed above the shell (forms, risk flow).
GoRoute _top(String path, Widget Function(GoRouterState) build) => GoRoute(
      path: path,
      parentNavigatorKey: _rootKey,
      builder: (_, state) => build(state),
    );

GoRoute _page(String path, Widget screen, {List<RouteBase> routes = const []}) =>
    GoRoute(path: path, builder: (_, _) => screen, routes: routes);

final routerProvider = Provider<GoRouter>((ref) {
  final auth = ValueNotifier(ref.read(authControllerProvider));
  ref
    ..listen(authControllerProvider, (_, next) => auth.value = next)
    ..onDispose(auth.dispose);

  const authPaths = {Routes.login, Routes.signUp, Routes.forgotPassword};

  return GoRouter(
    navigatorKey: _rootKey,
    initialLocation: Routes.home,
    refreshListenable: auth,
    redirect: (_, state) {
      final status = auth.value;
      if (status == AuthStatus.unknown) return null;
      final onAuth = authPaths.contains(state.matchedLocation);
      if (status == AuthStatus.signedOut && !onAuth) return Routes.login;
      if (status == AuthStatus.signedIn && onAuth) return Routes.home;
      return null;
    },
    routes: [
      _page(Routes.login, const LoginScreen()),
      _page(Routes.signUp, const SignUpScreen()),
      _page(Routes.forgotPassword, const ForgotPasswordScreen()),

      // Add/log forms and the risk flow open full-screen over the bottom nav.
      _top(Routes.addGlucose, (_) => const AddGlucoseScreen()),
      _top(Routes.addMeal, (s) => AddMealScreen(draft: s.extra as MealDraft?)),
      _top(Routes.visionAi, (_) => const VisionAiScreen()),
      _top(Routes.logWorkout, (_) => const LogWorkoutScreen()),
      _top(Routes.addWater, (_) => const AddWaterScreen()),
      _top(Routes.addMedication, (_) => const AddMedicationScreen()),
      _top(Routes.riskIntro, (_) => const RiskIntroScreen()),
      _top(Routes.riskQuiz, (_) => const RiskQuizScreen()),
      _top(Routes.riskResult, (s) => RiskResultScreen(result: s.extra! as CdcResult)),

      StatefulShellRoute.indexedStack(
        builder: (_, _, shell) => MainShell(shell: shell),
        branches: [
          StatefulShellBranch(routes: [
            _page(Routes.home, const HomeScreen(), routes: [
              _page('notifications', const NotificationsScreen()),
              _page('analytics', const AnalyticsScreen()),
            ]),
          ]),
          StatefulShellBranch(routes: [
            _page(Routes.chat, const ChatScreen()),
          ]),
          StatefulShellBranch(routes: [
            _page(Routes.track, const TrackingHubScreen(), routes: [
              _page('glucose', const GlucoseScreen()),
              _page('meals', const MealsScreen()),
              _page('exercise', const ExerciseScreen()),
              _page('water', const WaterScreen()),
              _page('medications', const MedicationsScreen()),
            ]),
          ]),
          StatefulShellBranch(routes: [
            _page(Routes.profile, const ProfileScreen(), routes: [
              _page('edit', const EditProfileScreen()),
              _page('settings', const SettingsScreen()),
            ]),
          ]),
        ],
      ),
    ],
  );
});

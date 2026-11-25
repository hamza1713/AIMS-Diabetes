import 'package:aims_diabetes/core/theme/app_theme.dart';
import 'package:aims_diabetes/core/widgets/state_views.dart';
import 'package:aims_diabetes/features/auth/presentation/auth_scaffold.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

void main() {
  setUpAll(() => GoogleFonts.config.allowRuntimeFetching = false);

  group('auth validators', () {
    test('email', () {
      expect(validateEmail(''), isNotNull);
      expect(validateEmail('not-an-email'), isNotNull);
      expect(validateEmail(' user@example.com '), isNull);
    });

    test('password needs 8+ chars', () {
      expect(validatePassword('short'), isNotNull);
      expect(validatePassword('longenough'), isNull);
    });
  });

  for (final (name, theme) in [
    ('light', AppTheme.light),
    ('dark', AppTheme.dark),
  ]) {
    testWidgets('ErrorStateView renders retry in $name theme', (tester) async {
      var retried = false;
      await tester.pumpWidget(MaterialApp(
        theme: theme(),
        home: Scaffold(
          body: ErrorStateView(
            message: 'No connection',
            onRetry: () => retried = true,
          ),
        ),
      ));
      expect(find.text('No connection'), findsOneWidget);
      await tester.tap(find.text('Try again'));
      expect(retried, isTrue);
    });
  }
}

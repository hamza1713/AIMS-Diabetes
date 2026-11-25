import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/theme/app_spacing.dart';
import '../data/auth_repository.dart';
import 'auth_scaffold.dart';

/// Figma "01c · Forgot Password".
class ForgotPasswordScreen extends ConsumerStatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  ConsumerState<ForgotPasswordScreen> createState() =>
      _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends ConsumerState<ForgotPasswordScreen> {
  final _form = GlobalKey<FormState>();
  final _email = TextEditingController();
  bool _busy = false;
  bool _sent = false;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    try {
      await ref.read(authRepositoryProvider).forgotPassword(_email.text.trim());
      if (mounted) setState(() => _sent = true);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(ApiException.from(e).message)));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AuthScaffold(
      showBack: true,
      title: _sent ? 'Check your email' : 'Forgot password?',
      subtitle: _sent
          ? 'If an account exists for ${_email.text.trim()}, we sent a reset link.'
          : "Enter your email and we'll send you a reset link",
      children: [
        if (!_sent) ...[
          Form(
            key: _form,
            child: TextFormField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(
                hintText: 'Email',
                prefixIcon: Icon(Icons.mail_outline_rounded),
              ),
              validator: validateEmail,
            ),
          ),
          const SizedBox(height: AppSpacing.xxl),
          FilledButton(
            onPressed: _busy ? null : _submit,
            child: Text(_busy ? 'Sending…' : 'Send reset link'),
          ),
        ] else
          FilledButton(
            onPressed: () => Navigator.of(context).maybePop(),
            child: const Text('Back to sign in'),
          ),
      ],
    );
  }
}

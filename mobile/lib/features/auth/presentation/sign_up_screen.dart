import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/theme/app_spacing.dart';
import '../application/auth_controller.dart';
import 'auth_scaffold.dart';

/// Figma "01b · Sign Up".
class SignUpScreen extends ConsumerStatefulWidget {
  const SignUpScreen({super.key});

  @override
  ConsumerState<SignUpScreen> createState() => _SignUpScreenState();
}

class _SignUpScreenState extends ConsumerState<SignUpScreen> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _agreed = false;
  bool _busy = false;

  @override
  void dispose() {
    for (final c in [_name, _email, _password, _confirm]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    if (!_agreed) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Please accept the terms to continue')));
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(authControllerProvider.notifier).register(
            _name.text.trim(),
            _email.text.trim(),
            _password.text,
          );
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
    const gap = SizedBox(height: AppSpacing.md);
    return AuthScaffold(
      showBack: true,
      title: 'Create account',
      subtitle: 'Start managing your diabetes with AI support',
      children: [
        Form(
          key: _form,
          child: Column(
            children: [
              TextFormField(
                controller: _name,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(
                  hintText: 'Full name',
                  prefixIcon: Icon(Icons.person_outline_rounded),
                ),
                validator: (v) =>
                    (v ?? '').trim().isEmpty ? 'Enter your name' : null,
              ),
              gap,
              TextFormField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(
                  hintText: 'Email',
                  prefixIcon: Icon(Icons.mail_outline_rounded),
                ),
                validator: validateEmail,
              ),
              gap,
              TextFormField(
                controller: _password,
                obscureText: true,
                decoration: const InputDecoration(
                  hintText: 'Password',
                  prefixIcon: Icon(Icons.lock_outline_rounded),
                ),
                validator: validatePassword,
              ),
              gap,
              TextFormField(
                controller: _confirm,
                obscureText: true,
                decoration: const InputDecoration(
                  hintText: 'Confirm password',
                  prefixIcon: Icon(Icons.lock_outline_rounded),
                ),
                validator: (v) =>
                    v != _password.text ? 'Passwords do not match' : null,
              ),
            ],
          ),
        ),
        CheckboxListTile(
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
          value: _agreed,
          onChanged: (v) => setState(() => _agreed = v ?? false),
          title: const Text('I agree to the Terms and Privacy Policy'),
        ),
        const SizedBox(height: AppSpacing.md),
        FilledButton(
          onPressed: _busy ? null : _submit,
          child: Text(_busy ? 'Creating account…' : 'Create account'),
        ),
      ],
    );
  }
}

import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../utils/format.dart';

/// Layout for every "Add …" form (Figma 17–21): scrolling fields with a
/// pinned primary button.
class FormScaffold extends StatelessWidget {
  const FormScaffold({
    super.key,
    required this.title,
    required this.children,
    required this.submitLabel,
    required this.onSubmit,
    this.busy = false,
  });

  final String title;
  final List<Widget> children;
  final String submitLabel;
  final VoidCallback? onSubmit;
  final bool busy;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(title)),
        body: ListView(
          padding: const EdgeInsets.all(AppSpacing.page),
          children: children,
        ),
        bottomNavigationBar: SafeArea(
          minimum: const EdgeInsets.all(AppSpacing.page),
          child: FilledButton(
            onPressed: busy ? null : onSubmit,
            child: busy
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.white),
                  )
                : Text(submitLabel),
          ),
        ),
      );
}

class FieldLabel extends StatelessWidget {
  const FieldLabel(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: AppSpacing.lg, bottom: AppSpacing.sm),
        child: Text(text, style: Theme.of(context).textTheme.titleMedium),
      );
}

/// Single-select pill chips ("When", meal type, intensity, form).
class ChoiceChips<T> extends StatelessWidget {
  const ChoiceChips({
    super.key,
    required this.options,
    required this.selected,
    required this.onSelected,
    required this.label,
  });

  final List<T> options;
  final T? selected;
  final ValueChanged<T> onSelected;
  final String Function(T) label;

  @override
  Widget build(BuildContext context) => Wrap(
        spacing: AppSpacing.sm,
        runSpacing: AppSpacing.sm,
        children: [
          for (final o in options)
            ChoiceChip(
              label: Text(label(o)),
              selected: o == selected,
              showCheckmark: false,
              labelStyle: TextStyle(
                color: o == selected ? Colors.white : null,
                fontWeight: FontWeight.w600,
              ),
              onSelected: (_) => onSelected(o),
            ),
        ],
      );
}

/// Date + time picker row.
class DateTimeField extends StatelessWidget {
  const DateTimeField({super.key, required this.value, required this.onChanged});
  final DateTime value;
  final ValueChanged<DateTime> onChanged;

  @override
  Widget build(BuildContext context) {
    Future<void> pickDate() async {
      final d = await showDatePicker(
        context: context,
        initialDate: value,
        firstDate: DateTime.now().subtract(const Duration(days: 365)),
        lastDate: DateTime.now(),
      );
      if (d != null) {
        onChanged(DateTime(d.year, d.month, d.day, value.hour, value.minute));
      }
    }

    Future<void> pickTime() async {
      final t = await showTimePicker(
          context: context, initialTime: TimeOfDay.fromDateTime(value));
      if (t != null) {
        onChanged(
            DateTime(value.year, value.month, value.day, t.hour, t.minute));
      }
    }

    return Row(
      children: [
        Expanded(
          child: OutlinedButton.icon(
            onPressed: pickDate,
            icon: const Icon(Icons.calendar_today_rounded, size: 18),
            label: Text(relativeDay(value)),
          ),
        ),
        const SizedBox(width: AppSpacing.md),
        Expanded(
          child: OutlinedButton.icon(
            onPressed: pickTime,
            icon: const Icon(Icons.schedule_rounded, size: 18),
            label: Text(fmtTime(value)),
          ),
        ),
      ],
    );
  }
}

/// Big centered numeric input (glucose value, custom water amount).
class BigNumberField extends StatelessWidget {
  const BigNumberField({
    super.key,
    required this.controller,
    required this.unit,
    this.validator,
  });

  final TextEditingController controller;
  final String unit;
  final FormFieldValidator<String>? validator;

  @override
  Widget build(BuildContext context) => Column(
        children: [
          TextFormField(
            controller: controller,
            autofocus: true,
            textAlign: TextAlign.center,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            style: Theme.of(context).textTheme.displaySmall?.copyWith(
                fontWeight: FontWeight.w700, color: AppColors.primary),
            decoration: const InputDecoration(
              hintText: '0',
              filled: false,
              border: InputBorder.none,
              enabledBorder: InputBorder.none,
              focusedBorder: InputBorder.none,
            ),
            validator: validator,
          ),
          Text(unit, style: Theme.of(context).textTheme.bodySmall),
        ],
      );
}

String? requiredNumber(String? v, {double min = 0, double max = double.infinity}) {
  final n = double.tryParse((v ?? '').trim());
  if (n == null) return 'Enter a number';
  if (n < min || n > max) return 'Must be between ${fmtNum(min)} and ${fmtNum(max)}';
  return null;
}

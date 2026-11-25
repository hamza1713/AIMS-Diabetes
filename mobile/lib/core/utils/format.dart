import 'package:intl/intl.dart';

final _time = DateFormat.jm();
final _dayMonth = DateFormat('d MMM');
final _weekday = DateFormat.E();

String fmtTime(DateTime d) => _time.format(d);
String fmtDayMonth(DateTime d) => _dayMonth.format(d);
String fmtWeekday(DateTime d) => _weekday.format(d);

String fmtNum(num? v, {int decimals = 0}) =>
    v == null ? '—' : v.toStringAsFixed(decimals);

bool isSameDay(DateTime a, DateTime b) =>
    a.year == b.year && a.month == b.month && a.day == b.day;

String greeting([DateTime? now]) {
  final h = (now ?? DateTime.now()).hour;
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

/// "Today", "Yesterday" or "12 Mar".
String relativeDay(DateTime d, [DateTime? now]) {
  final today = now ?? DateTime.now();
  if (isSameDay(d, today)) return 'Today';
  if (isSameDay(d, today.subtract(const Duration(days: 1)))) return 'Yesterday';
  return fmtDayMonth(d);
}

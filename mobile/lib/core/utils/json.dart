/// Lenient JSON readers. The backend is evolving, so models read fields
/// through these helpers (with alternate keys) instead of hard casts.
typedef Json = Map<String, dynamic>;

dynamic _pick(Json j, List<String> keys) {
  for (final k in keys) {
    if (j.containsKey(k) && j[k] != null) return j[k];
  }
  return null;
}

double? jNum(Json j, List<String> keys) {
  final v = _pick(j, keys);
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v);
  return null;
}

int? jInt(Json j, List<String> keys) => jNum(j, keys)?.round();

String? jStr(Json j, List<String> keys) => _pick(j, keys)?.toString();

bool jBool(Json j, List<String> keys, {bool fallback = false}) {
  final v = _pick(j, keys);
  if (v is bool) return v;
  if (v is num) return v != 0;
  if (v is String) return v == 'true' || v == '1';
  return fallback;
}

DateTime? jDate(Json j, List<String> keys) {
  final v = jStr(j, keys);
  if (v == null) return null;
  final parsed = DateTime.tryParse(v);
  // Backend stores naive UTC timestamps.
  if (parsed != null && !v.endsWith('Z') && !v.contains('+')) {
    return DateTime.utc(parsed.year, parsed.month, parsed.day, parsed.hour,
            parsed.minute, parsed.second)
        .toLocal();
  }
  return parsed?.toLocal();
}

Json jObj(Json j, List<String> keys) {
  final v = _pick(j, keys);
  return v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
}

List<Json> jList(dynamic v, [List<String> keys = const []]) {
  var data = v;
  if (data is Map && keys.isNotEmpty) {
    data = _pick(Map<String, dynamic>.from(data), keys);
  }
  if (data is! List) return const [];
  return [
    for (final e in data)
      if (e is Map) Map<String, dynamic>.from(e),
  ];
}

/// ISO date (yyyy-MM-dd) for query parameters.
String isoDay(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

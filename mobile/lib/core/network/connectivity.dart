import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// `true` while the device has no network (Figma "No connection" state).
final offlineProvider = StreamProvider<bool>((ref) async* {
  final c = Connectivity();
  bool offline(List<ConnectivityResult> r) =>
      r.isEmpty || r.every((x) => x == ConnectivityResult.none);
  yield offline(await c.checkConnectivity());
  yield* c.onConnectivityChanged.map(offline);
});

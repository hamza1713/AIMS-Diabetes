import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/api_client.dart';
import 'state_views.dart';

/// Renders an [AsyncValue] with the app's skeleton / error states.
class AsyncView<T> extends StatelessWidget {
  const AsyncView({
    super.key,
    required this.value,
    required this.data,
    this.onRetry,
    this.skeletonCount = 4,
  });

  final AsyncValue<T> value;
  final Widget Function(T data) data;
  final VoidCallback? onRetry;
  final int skeletonCount;

  @override
  Widget build(BuildContext context) => value.when(
        // Keep showing old data while refreshing.
        skipLoadingOnRefresh: true,
        skipLoadingOnReload: true,
        data: data,
        loading: () => SkeletonList(count: skeletonCount),
        error: (e, _) => ErrorStateView(
          message: ApiException.from(e).message,
          onRetry: onRetry,
        ),
      );
}

/// Shows a snackbar with a readable error.
void showError(BuildContext context, Object error) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(ApiException.from(error).message)),
  );
}

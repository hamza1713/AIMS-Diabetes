import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../domain/cdc_risk.dart';

Color riskColor(RiskBand b) => switch (b) {
      RiskBand.low => AppColors.success,
      RiskBand.moderate => AppColors.warning,
      RiskBand.high => AppColors.danger,
    };

/// Round score badge ("4/11") coloured by band.
class RiskBadge extends StatelessWidget {
  const RiskBadge({super.key, required this.band, required this.score, this.radius = 26});
  final RiskBand band;
  final int score;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final c = riskColor(band);
    return CircleAvatar(
      radius: radius,
      backgroundColor: c.withValues(alpha: 0.14),
      child: Text('$score/${CdcResult.maxScore}',
          style: TextStyle(
              color: c, fontWeight: FontWeight.w700, fontSize: radius * 0.5)),
    );
  }
}

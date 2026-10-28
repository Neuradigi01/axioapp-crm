import 'package:freezed_annotation/freezed_annotation.dart';

part 'dashboard_data.freezed.dart';
part 'dashboard_data.g.dart';

@freezed
class DashboardData with _$DashboardData {
  const factory DashboardData({
    @JsonKey(name: 'first_name') required String firstName,
    @JsonKey(name: 'last_name') required String lastName,
    required String email,
    @JsonKey(name: 'joining_date') String? joiningDate,
    @JsonKey(name: 'two_factor_enabled') @Default(false) bool twoFactorEnabled,
    @JsonKey(name: 'referral_count') @Default(0) int referralCount,
    @JsonKey(name: 'open_tickets') @Default(0) int openTickets,
    @JsonKey(name: 'profile_image') String? profileImage,
  }) = _DashboardData;

  factory DashboardData.fromJson(Map<String, dynamic> json) =>
      _$DashboardDataFromJson(json);
}

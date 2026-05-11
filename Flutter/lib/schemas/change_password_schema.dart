import 'package:freezed_annotation/freezed_annotation.dart';

part 'change_password_schema.freezed.dart';
part 'change_password_schema.g.dart';

@freezed
class ChangePasswordRequest with _$ChangePasswordRequest {
  const factory ChangePasswordRequest({
    @JsonKey(name: 'old_password') required String oldPassword,
    @JsonKey(name: 'new_password') required String newPassword,
  }) = _ChangePasswordRequest;

  factory ChangePasswordRequest.fromJson(Map<String, dynamic> json) =>
      _$ChangePasswordRequestFromJson(json);
}

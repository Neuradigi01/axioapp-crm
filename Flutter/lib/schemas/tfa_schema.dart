import 'package:freezed_annotation/freezed_annotation.dart';

part 'tfa_schema.freezed.dart';
part 'tfa_schema.g.dart';

// -- Send Setup OTP ─────────────────────────────────────────────────────────

@freezed
class SendSetupOtpRequest with _$SendSetupOtpRequest {
  const factory SendSetupOtpRequest({
    required String method,
  }) = _SendSetupOtpRequest;

  factory SendSetupOtpRequest.fromJson(Map<String, dynamic> json) =>
      _$SendSetupOtpRequestFromJson(json);
}

// -- Verify and Enable ──────────────────────────────────────────────────────

@freezed
class VerifyAndEnableRequest with _$VerifyAndEnableRequest {
  const factory VerifyAndEnableRequest({
    required String code,
    required String method,
  }) = _VerifyAndEnableRequest;

  factory VerifyAndEnableRequest.fromJson(Map<String, dynamic> json) =>
      _$VerifyAndEnableRequestFromJson(json);
}

// -- Change Method ──────────────────────────────────────────────────────────

@freezed
class ChangeMethodRequest with _$ChangeMethodRequest {
  const factory ChangeMethodRequest({
    @JsonKey(name: 'new_method') required String newMethod,
  }) = _ChangeMethodRequest;

  factory ChangeMethodRequest.fromJson(Map<String, dynamic> json) =>
      _$ChangeMethodRequestFromJson(json);
}

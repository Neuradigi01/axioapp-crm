import 'package:freezed_annotation/freezed_annotation.dart';

part 'login_history_schema.freezed.dart';
part 'login_history_schema.g.dart';

@freezed
class LoginHistoryListRequest with _$LoginHistoryListRequest {
  const factory LoginHistoryListRequest({
    @JsonKey(name: 'page_index') @Default(1) int pageIndex,
    @JsonKey(name: 'page_size') @Default(10) int pageSize,
  }) = _LoginHistoryListRequest;

  factory LoginHistoryListRequest.fromJson(Map<String, dynamic> json) =>
      _$LoginHistoryListRequestFromJson(json);
}

@freezed
class LogoutSessionRequest with _$LogoutSessionRequest {
  const factory LogoutSessionRequest({
    @JsonKey(name: 'token_id') required int tokenId,
  }) = _LogoutSessionRequest;

  factory LogoutSessionRequest.fromJson(Map<String, dynamic> json) =>
      _$LogoutSessionRequestFromJson(json);
}

import 'package:template_app/core/constants/api_endpoints.dart';
import 'package:template_app/core/network/api_helper.dart';
import 'package:template_app/core/network/api_response.dart';

/// API service for action verification (2FA for sensitive actions).
class ActionVerifyApiService {
  ActionVerifyApiService(this._apiHelper);
  final ApiHelper _apiHelper;

  /// Sends an OTP for action verification.
  ///
  /// [method] — the 2FA method: 'email' or 'sms'.
  Future<ApiResponse> sendOtp({required String method}) async {
    return _apiHelper.post(
      ApiEndpoints.actionVerifySendOtp,
      data: {'method': method},
    );
  }

  /// Verifies the OTP code and returns an action token.
  ///
  /// [code] — the 6-digit OTP code.
  /// [method] — the 2FA method used: 'authenticator', 'email', or 'sms'.
  Future<ApiResponse> verify({
    required String code,
    required String method,
  }) async {
    return _apiHelper.post(
      ApiEndpoints.actionVerify,
      data: {'code': code, 'method': method},
    );
  }

  /// Fetches the user's 2FA status (available methods, current method).
  Future<ApiResponse> getTfaStatus() async {
    return _apiHelper.get(ApiEndpoints.tfaStatus);
  }
}

import 'package:template_app/core/constants/api_endpoints.dart';
import 'package:template_app/core/network/api_helper.dart';
import 'package:template_app/core/network/api_response.dart';
import 'package:template_app/schemas/tfa_schema.dart';

/// API service for two-factor authentication management endpoints.
class TwoFactorApiService {
  TwoFactorApiService(this._apiHelper);
  final ApiHelper _apiHelper;

  /// Fetches the user's current 2FA status and available methods.
  Future<ApiResponse> getStatus() async {
    return _apiHelper.get(ApiEndpoints.tfaStatus);
  }

  /// Initiates authenticator setup — returns QR code and secret key.
  Future<ApiResponse> setupAuthenticator() async {
    return _apiHelper.post(ApiEndpoints.tfaSetupAuthenticator);
  }

  /// Sends an OTP to the user's email or phone for 2FA setup.
  Future<ApiResponse> sendSetupOtp(SendSetupOtpRequest request) async {
    return _apiHelper.post(
      ApiEndpoints.tfaSendSetupOtp,
      data: request.toJson(),
    );
  }

  /// Verifies the OTP/authenticator code and enables 2FA.
  Future<ApiResponse> verifyAndEnable(VerifyAndEnableRequest request) async {
    return _apiHelper.post(
      ApiEndpoints.tfaVerifyAndEnable,
      data: request.toJson(),
    );
  }

  /// Disables 2FA for the user (requires action token).
  Future<ApiResponse> disable() async {
    return _apiHelper.post(ApiEndpoints.tfaDisable);
  }

  /// Changes the 2FA method (requires action token).
  Future<ApiResponse> changeMethod(ChangeMethodRequest request) async {
    return _apiHelper.post(
      ApiEndpoints.tfaChangeMethod,
      data: request.toJson(),
    );
  }
}

import 'package:template_app/core/constants/api_endpoints.dart';
import 'package:template_app/core/network/api_helper.dart';
import 'package:template_app/core/network/api_response.dart';
import 'package:template_app/schemas/auth_schema.dart';

/// API service for authentication endpoints.
class AuthApiService {
  AuthApiService(this._apiHelper);
  final ApiHelper _apiHelper;

  /// Authenticates a user with credentials and optional 2FA/CAPTCHA.
  Future<ApiResponse> login(LoginRequest request) async {
    return _apiHelper.post(ApiEndpoints.login, data: request.toJson());
  }

  /// Switches 2FA method during login (try another way).
  Future<ApiResponse> tryAnotherWay2fa(TryAnotherWayRequest request) async {
    return _apiHelper.post(
      ApiEndpoints.tfaTryAnotherWay,
      data: request.toJson(),
    );
  }

  /// Requests a password reset email.
  Future<ApiResponse> forgotPassword(ForgotPasswordRequest request) async {
    return _apiHelper.post(
      ApiEndpoints.forgotPassword,
      data: request.toJson(),
    );
  }

  /// Resets password using a token from the reset email.
  Future<ApiResponse> resetPassword(ResetPasswordRequest request) async {
    return _apiHelper.post(
      ApiEndpoints.resetPassword,
      data: request.toJson(),
    );
  }

  /// Verifies an email address using a token from the verification email.
  Future<ApiResponse> verifyEmail(String token) async {
    return _apiHelper.post(
      ApiEndpoints.verifyContactVerifyEmail,
      data: {'token': token},
    );
  }

  /// Sends an OTP for contact verification (email or SMS).
  Future<ApiResponse> sendContactVerificationOtp(SendOtpRequest request) async {
    return _apiHelper.post(
      ApiEndpoints.verifyContactSendOtp,
      data: request.toJson(),
    );
  }

  /// Registers a new user account.
  Future<ApiResponse> register(RegisterRequest request) async {
    return _apiHelper.post(ApiEndpoints.register, data: request.toJson());
  }

  /// Fetches CAPTCHA configuration (type, image, site key).
  Future<ApiResponse> getCaptcha() async {
    return _apiHelper.get(ApiEndpoints.captcha);
  }
}

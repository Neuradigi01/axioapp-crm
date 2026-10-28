import 'package:template_app/core/constants/api_endpoints.dart';
import 'package:template_app/core/network/api_helper.dart';
import 'package:template_app/core/network/api_response.dart';
import 'package:template_app/schemas/login_history_schema.dart';

/// API service for login history endpoints.
class LoginHistoryApiService {
  LoginHistoryApiService(this._apiHelper);
  final ApiHelper _apiHelper;

  /// Fetches paginated login history records.
  Future<ApiResponse> getList(LoginHistoryListRequest request) async {
    return _apiHelper.post(ApiEndpoints.loginHistoryList,
        data: request.toJson());
  }

  /// Logs out a specific session by token ID.
  Future<ApiResponse> logoutSession(LogoutSessionRequest request) async {
    return _apiHelper.post(ApiEndpoints.loginHistoryLogoutSession,
        data: request.toJson());
  }

  /// Logs out the current session.
  Future<ApiResponse> logout() async {
    return _apiHelper.post(ApiEndpoints.logout);
  }
}

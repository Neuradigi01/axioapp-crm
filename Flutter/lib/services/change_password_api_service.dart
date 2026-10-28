import 'package:template_app/core/constants/api_endpoints.dart';
import 'package:template_app/core/network/api_helper.dart';
import 'package:template_app/core/network/api_response.dart';
import 'package:template_app/schemas/change_password_schema.dart';

/// API service for change password endpoint.
class ChangePasswordApiService {
  ChangePasswordApiService(this._apiHelper);
  final ApiHelper _apiHelper;

  /// Changes the user's password.
  Future<ApiResponse> changePassword(ChangePasswordRequest request) async {
    return _apiHelper.post(ApiEndpoints.changePassword, data: request.toJson());
  }
}

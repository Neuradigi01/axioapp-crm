import 'package:template_app/core/constants/api_endpoints.dart';
import 'package:template_app/core/network/api_helper.dart';
import 'package:template_app/core/network/api_response.dart';

/// API service for application configuration.
class AppConfigApiService {
  AppConfigApiService(this._apiHelper);
  final ApiHelper _apiHelper;

  /// Fetches the application configuration (CAPTCHA, email, SMS, etc.).
  Future<ApiResponse> getAppConfig() async {
    return _apiHelper.get(ApiEndpoints.appConfig);
  }
}

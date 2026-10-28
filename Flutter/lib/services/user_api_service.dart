import 'package:template_app/core/constants/api_endpoints.dart';
import 'package:template_app/core/network/api_helper.dart';
import 'package:template_app/core/network/api_response.dart';
import 'package:template_app/schemas/user_schema.dart';

/// API service for user profile and dashboard endpoints.
class UserApiService {
  UserApiService(this._apiHelper);
  final ApiHelper _apiHelper;

  /// Fetches the user's dashboard summary data.
  Future<ApiResponse> getDashboard() async {
    return _apiHelper.get(ApiEndpoints.userDashboard);
  }

  /// Fetches the user's full profile.
  Future<ApiResponse> getProfile() async {
    return _apiHelper.get(ApiEndpoints.userProfile);
  }

  /// Updates the user's profile.
  Future<ApiResponse> updateProfile(ProfileUpdateRequest request) async {
    return _apiHelper.put(ApiEndpoints.userProfile, data: request.toJson());
  }

  /// Uploads a new profile image.
  Future<ApiResponse> uploadProfileImage(String filePath) async {
    return _apiHelper.uploadFile(
      ApiEndpoints.userProfileImage,
      filePath: filePath,
      fieldName: 'file',
    );
  }

  /// Removes the user's profile image.
  Future<ApiResponse> removeProfileImage() async {
    return _apiHelper.delete(ApiEndpoints.userProfileImage);
  }
}

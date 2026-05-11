import 'package:dio/dio.dart';

import 'package:template_app/core/network/api_response.dart';

/// Dio wrapper providing typed CRUD methods and file upload.
///
/// All HTTP calls in the app go through this class.
/// Returns [ApiResponse] matching the backend's standard format.
class ApiHelper {
  ApiHelper(this._dio);
  final Dio _dio;

  Future<ApiResponse> get(
    String path, {
    Map<String, dynamic>? queryParams,
  }) async {
    final response = await _dio.get(path, queryParameters: queryParams);
    return ApiResponse.fromJson(response.data as Map<String, dynamic>);
  }

  Future<ApiResponse> post(
    String path, {
    dynamic data,
    Map<String, dynamic>? queryParams,
  }) async {
    final response = await _dio.post(
      path,
      data: data,
      queryParameters: queryParams,
    );
    return ApiResponse.fromJson(response.data as Map<String, dynamic>);
  }

  Future<ApiResponse> put(
    String path, {
    dynamic data,
    Map<String, dynamic>? queryParams,
  }) async {
    final response = await _dio.put(
      path,
      data: data,
      queryParameters: queryParams,
    );
    return ApiResponse.fromJson(response.data as Map<String, dynamic>);
  }

  Future<ApiResponse> delete(
    String path, {
    Map<String, dynamic>? queryParams,
  }) async {
    final response = await _dio.delete(path, queryParameters: queryParams);
    return ApiResponse.fromJson(response.data as Map<String, dynamic>);
  }

  Future<ApiResponse> uploadFile(
    String path, {
    required String filePath,
    required String fieldName,
    Map<String, dynamic>? extraFields,
  }) async {
    final formData = FormData.fromMap({
      fieldName: await MultipartFile.fromFile(filePath),
      ...?extraFields,
    });
    final response = await _dio.post(path, data: formData);
    return ApiResponse.fromJson(response.data as Map<String, dynamic>);
  }
}

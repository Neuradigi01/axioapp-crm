/// Standard API response model matching the FastAPI backend format.
///
/// Backend returns: `{ success: bool, message: str, data: ..., data_count: int? }`
class ApiResponse {
  final bool success;
  final String message;
  final dynamic data;
  final int? dataCount;

  const ApiResponse({
    required this.success,
    required this.message,
    this.data,
    this.dataCount,
  });

  factory ApiResponse.fromJson(Map<String, dynamic> json) {
    return ApiResponse(
      success: json['success'] as bool,
      message: json['message'] as String? ?? '',
      data: json['data'],
      dataCount: json['data_count'] as int?,
    );
  }
}

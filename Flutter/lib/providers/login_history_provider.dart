import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:template_app/models/login_history.dart';
import 'package:template_app/providers/service_providers.dart';
import 'package:template_app/schemas/login_history_schema.dart';

/// State for paginated login history.
class LoginHistoryState {
  const LoginHistoryState({
    this.records = const [],
    this.totalCount = 0,
    this.pageIndex = 1,
    this.pageSize = 10,
    this.isLoading = false,
    this.error,
  });

  final List<LoginHistoryRecord> records;
  final int totalCount;
  final int pageIndex;
  final int pageSize;
  final bool isLoading;
  final String? error;

  int get totalPages => (totalCount / pageSize).ceil().clamp(1, 999999);

  LoginHistoryState copyWith({
    List<LoginHistoryRecord>? records,
    int? totalCount,
    int? pageIndex,
    int? pageSize,
    bool? isLoading,
    String? error,
  }) {
    return LoginHistoryState(
      records: records ?? this.records,
      totalCount: totalCount ?? this.totalCount,
      pageIndex: pageIndex ?? this.pageIndex,
      pageSize: pageSize ?? this.pageSize,
      isLoading: isLoading ?? this.isLoading,
      error: error,
    );
  }
}

/// Notifier managing paginated login history data.
class LoginHistoryNotifier extends StateNotifier<LoginHistoryState> {
  LoginHistoryNotifier(this._ref) : super(const LoginHistoryState());

  final Ref _ref;

  /// Fetches login history for the given page.
  Future<void> fetchPage({int? pageIndex, int? pageSize}) async {
    final newPageIndex = pageIndex ?? state.pageIndex;
    final newPageSize = pageSize ?? state.pageSize;

    state = state.copyWith(
      isLoading: true,
      error: null,
      pageIndex: newPageIndex,
      pageSize: newPageSize,
    );

    final api = _ref.read(loginHistoryApiServiceProvider);
    final request = LoginHistoryListRequest(
      pageIndex: newPageIndex,
      pageSize: newPageSize,
    );

    final response = await api.getList(request);

    if (!response.success) {
      state = state.copyWith(isLoading: false, error: response.message);
      return;
    }

    final data = response.data;
    final List<LoginHistoryRecord> records;
    if (data is List) {
      records = data
          .map((e) =>
              LoginHistoryRecord.fromJson(e as Map<String, dynamic>))
          .toList();
    } else {
      records = [];
    }

    state = state.copyWith(
      records: records,
      totalCount: response.dataCount ?? records.length,
      isLoading: false,
    );
  }

  /// Logs out a specific session and refreshes the list.
  Future<bool> logoutSession(int tokenId) async {
    final api = _ref.read(loginHistoryApiServiceProvider);
    final response = await api.logoutSession(
      LogoutSessionRequest(tokenId: tokenId),
    );

    if (response.success) {
      await fetchPage();
    }

    return response.success;
  }
}

/// Provider for login history state with pagination.
final loginHistoryProvider =
    StateNotifierProvider<LoginHistoryNotifier, LoginHistoryState>((ref) {
  return LoginHistoryNotifier(ref);
});

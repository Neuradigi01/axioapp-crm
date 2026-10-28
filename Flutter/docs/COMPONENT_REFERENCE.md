# Flutter App — Component Reference

Widget contracts, architecture patterns, routing, HTTP, state management, and page layout system.

---

## Widget Contract

Every widget in this project MUST follow:

1. **Const constructor** — use `const` keyword if all fields are final
2. **`super.key`** — always accept key parameter
3. **Typed props** — no `dynamic`, no `Object`
4. **Single responsibility** — one widget, one job
5. **Decompose large builds** — extract private `_build*` methods if build > 80 lines
6. **Dispose controllers** — TextEditingController, ScrollController, AnimationController
7. **Use Riverpod** — `ConsumerWidget` or `ConsumerStatefulWidget` when accessing providers

### Screen Widget Template
```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class FeatureScreen extends ConsumerWidget {
  const FeatureScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    
    return Scaffold(
      body: // ...
    );
  }
}
```

### Stateful Screen Template (with form)
```dart
class FeatureFormScreen extends ConsumerStatefulWidget {
  const FeatureFormScreen({super.key});

  @override
  ConsumerState<FeatureFormScreen> createState() => _FeatureFormScreenState();
}

class _FeatureFormScreenState extends ConsumerState<FeatureFormScreen> {
  final _formKey = GlobalKey<FormState>();
  final _fieldController = TextEditingController();
  bool _isLoading = false;

  @override
  void dispose() {
    _fieldController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Form(
        key: _formKey,
        child: // ...
      ),
    );
  }

  Future<void> _handleSubmit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _isLoading = true);
    try {
      // API call via provider or service
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }
}
```

---

## Per-Feature Folder Structure

```
lib/features/auth/
├── screens/
│   ├── login_screen.dart
│   ├── register_screen.dart
│   ├── forgot_password_screen.dart
│   ├── reset_password_screen.dart
│   ├── two_factor_screen.dart
│   ├── verify_email_screen.dart
│   └── email_verification_notice_screen.dart
└── widgets/
    ├── auth_card_widget.dart
    └── otp_input_widget.dart
```

```
lib/features/user/
├── screens/
│   ├── dashboard_screen.dart
│   ├── profile_screen.dart
│   ├── security_screen.dart
│   ├── change_password_screen.dart
│   └── login_history_screen.dart
└── widgets/
    ├── dashboard_tile_widget.dart
    └── profile_image_widget.dart
```

```
lib/features/shared/
├── screens/
│   ├── ticket_list_screen.dart
│   ├── compose_ticket_screen.dart
│   └── view_ticket_screen.dart
└── widgets/
    ├── tfa_settings_widget.dart
    ├── login_history_table_widget.dart
    ├── change_password_form_widget.dart
    ├── ticket_thread_widget.dart
    └── attachment_list_widget.dart
```

---

## Routing — GoRouter

### Route Structure
```dart
// lib/core/router/app_router.dart
final appRouter = GoRouter(
  initialLocation: '/login',
  redirect: _globalRedirect,
  routes: [
    // === Auth Routes (no shell) ===
    GoRoute(
      name: AppRoutes.login,
      path: '/login',
      builder: (_, __) => const LoginScreen(),
    ),
    GoRoute(
      name: AppRoutes.register,
      path: '/register',
      builder: (_, __) => const RegisterScreen(),
    ),
    // ... other auth routes

    // === User Routes (with UserLayout shell) ===
    ShellRoute(
      builder: (_, __, child) => UserLayout(child: child),
      routes: [
        GoRoute(
          name: AppRoutes.userDashboard,
          path: '/user/dashboard',
          builder: (_, __) => const DashboardScreen(),
        ),
        GoRoute(
          name: AppRoutes.userProfile,
          path: '/user/profile',
          builder: (_, __) => const ProfileScreen(),
        ),
        // ... other user routes
      ],
    ),
  ],
);
```

### Route Names (Constants)
```dart
// lib/core/constants/app_routes.dart
class AppRoutes {
  // Auth
  static const login = 'login';
  static const register = 'register';
  static const forgotPassword = 'forgot-password';
  static const resetPassword = 'reset-password';
  static const twoFactor = 'two-factor';
  static const verifyEmail = 'verify-email';
  static const emailVerificationNotice = 'email-verification-notice';
  
  // User
  static const userDashboard = 'user-dashboard';
  static const userProfile = 'user-profile';
  static const userSecurity = 'user-security';
  static const userChangePassword = 'user-change-password';
  static const userLoginHistory = 'user-login-history';
  
  // Support
  static const ticketList = 'ticket-list';
  static const composeTicket = 'compose-ticket';
  static const viewTicket = 'view-ticket';
}
```

### Dynamic Routes from Backend
```dart
// lib/core/services/routes_helper_service.dart
// Routes are loaded from /api/routes/config on app startup
// RoutesHelper maps control_id → path
// Screens use RoutesHelper.getPath('control_id') for navigation

class RoutesHelper {
  static final Map<String, RouteConfig> _routes = {};

  static Future<void> loadRoutes(List<RouteConfig> routes) async {
    for (final route in routes) {
      _routes[route.controlId] = route;
    }
  }

  static String getPath(String controlId) {
    return _routes[controlId]?.path ?? '/';
  }

  static RouteConfig? getRoute(String controlId) {
    return _routes[controlId];
  }

  static List<RouteConfig> getMenuItems(String role, String accessRights) {
    // Filter routes based on role and access rights
    // Return ordered list for sidebar menu
  }
}
```

### Navigation in Screens
```dart
// GOOD — use GoRouter context extensions
context.goNamed(AppRoutes.userDashboard);
context.pushNamed(AppRoutes.viewTicket, pathParameters: {'id': ticketId});
context.pop();

// GOOD — with RoutesHelper for dynamic paths
context.go(RoutesHelper.getPath('user_dashboard'));

// BAD — never hardcode
context.go('/user/dashboard'); // FORBIDDEN
```

### Route Guards
```dart
// lib/core/guards/auth_guard.dart
String? _globalRedirect(BuildContext context, GoRouterState state) {
  final authState = // read from Riverpod container
  final isLoggedIn = authState.isAuthenticated;
  final isAuthRoute = state.matchedLocation.startsWith('/login') ||
                      state.matchedLocation.startsWith('/register');

  if (!isLoggedIn && !isAuthRoute) return '/login';
  if (isLoggedIn && isAuthRoute) return '/user/dashboard';
  return null; // no redirect
}
```

---

## HTTP / Network Layer

### ApiHelper (Dio Wrapper)
```dart
// lib/core/network/api_helper.dart
class ApiHelper {
  ApiHelper(this._dio);
  final Dio _dio;

  Future<ApiResponse> get(String path, {Map<String, dynamic>? queryParams}) async {
    final response = await _dio.get(path, queryParameters: queryParams);
    return ApiResponse.fromJson(response.data);
  }

  Future<ApiResponse> post(String path, {dynamic data}) async {
    final response = await _dio.post(path, data: data);
    return ApiResponse.fromJson(response.data);
  }

  Future<ApiResponse> put(String path, {dynamic data}) async {
    final response = await _dio.put(path, data: data);
    return ApiResponse.fromJson(response.data);
  }

  Future<ApiResponse> delete(String path) async {
    final response = await _dio.delete(path);
    return ApiResponse.fromJson(response.data);
  }

  Future<ApiResponse> uploadFile(String path, {
    required String filePath,
    required String fieldName,
    Map<String, dynamic>? extraFields,
  }) async {
    final formData = FormData.fromMap({
      fieldName: await MultipartFile.fromFile(filePath),
      ...?extraFields,
    });
    final response = await _dio.post(path, data: formData);
    return ApiResponse.fromJson(response.data);
  }
}
```

### ApiResponse Model
```dart
// lib/core/network/api_response.dart
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
      message: json['message'] as String,
      data: json['data'],
      dataCount: json['data_count'] as int?,
    );
  }
}
```

### Auth Interceptor
```dart
// lib/core/network/auth_interceptor.dart
class AuthInterceptor extends Interceptor {
  AuthInterceptor(this._authService);
  final AuthService _authService;

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    final token = _authService.token;
    if (token != null) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    if (err.response?.statusCode == 401) {
      _authService.logout();
      // Navigate to login
    }
    handler.next(err);
  }
}
```

### API Service Template
```dart
// lib/services/user_api_service.dart
class UserApiService {
  UserApiService(this._apiHelper);
  final ApiHelper _apiHelper;

  Future<ApiResponse> getDashboard() {
    return _apiHelper.get('/user/dashboard');
  }

  Future<ApiResponse> getProfile() {
    return _apiHelper.get('/user/profile');
  }

  Future<ApiResponse> updateProfile(ProfileUpdateRequest request) {
    return _apiHelper.put('/user/profile', data: request.toJson());
  }

  Future<ApiResponse> uploadProfileImage(String filePath) {
    return _apiHelper.uploadFile(
      '/user/profile/image',
      filePath: filePath,
      fieldName: 'file',
    );
  }

  Future<ApiResponse> removeProfileImage() {
    return _apiHelper.delete('/user/profile/image');
  }
}
```

---

## State Management Patterns

### Simple Async Data (FutureProvider)
```dart
// Provider
final userDashboardProvider = FutureProvider.autoDispose<DashboardData>((ref) async {
  final apiService = ref.read(userApiServiceProvider);
  final response = await apiService.getDashboard();
  if (!response.success) throw Exception(response.message);
  return DashboardData.fromJson(response.data);
});

// Screen usage
class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dashboardAsync = ref.watch(userDashboardProvider);
    
    return dashboardAsync.when(
      data: (data) => _buildContent(data),
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, _) => Center(child: Text(error.toString())),
    );
  }
}
```

### Complex State (StateNotifier)
```dart
// State class
@freezed
class AuthState with _$AuthState {
  const factory AuthState({
    @Default(false) bool isAuthenticated,
    @Default(false) bool isLoading,
    String? token,
    String? userId,
    String? role,
    String? errorMessage,
  }) = _AuthState;
}

// Notifier
class AuthNotifier extends StateNotifier<AuthState> {
  AuthNotifier(this._ref) : super(const AuthState());
  final Ref _ref;

  Future<bool> login(LoginRequest request) async {
    state = state.copyWith(isLoading: true, errorMessage: null);
    final apiService = _ref.read(authApiServiceProvider);
    final response = await apiService.login(request);
    
    if (response.success) {
      final token = response.data['token'];
      await _ref.read(authServiceProvider).saveToken(token);
      state = state.copyWith(
        isAuthenticated: true,
        isLoading: false,
        token: token,
        userId: response.data['user_id'],
        role: response.data['role'],
      );
      return true;
    } else {
      state = state.copyWith(isLoading: false, errorMessage: response.message);
      return false;
    }
  }

  void logout() {
    _ref.read(authServiceProvider).clearToken();
    state = const AuthState();
  }
}

// Provider
final authNotifierProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  return AuthNotifier(ref);
});
```

### Pagination Pattern
```dart
// State
@freezed
class PaginatedState<T> with _$PaginatedState<T> {
  const factory PaginatedState({
    @Default([]) List<T> items,
    @Default(0) int totalCount,
    @Default(0) int pageIndex,
    @Default(10) int pageSize,
    @Default(false) bool isLoading,
    String? errorMessage,
  }) = _PaginatedState<T>;

  bool get hasMore => items.length < totalCount;
}
```

---

## Shared Widget Library

### Reusable Widgets (in `lib/shared/widgets/`)

| Widget | Purpose |
|--------|---------|
| `AppButton` | Primary/secondary/text buttons with loading state |
| `AppTextField` | Themed TextFormField with label, validation |
| `AppCard` | Styled card container (auth cards, form cards) |
| `AppPageLayout` | Standard page wrapper with title, filters, content |
| `AppFormCard` | Card wrapper for form pages |
| `AppLoadingIndicator` | Consistent loading spinner |
| `AppErrorWidget` | Error display with retry button |
| `AppEmptyState` | Empty data state illustration |
| `AppStatusBadge` | Colored badge (Active, Inactive, etc.) |
| `AppConfirmDialog` | Yes/No confirmation dialog |
| `AppSnackbar` | Themed snackbar helper |
| `AppFileUpload` | File picker with preview |
| `AppPagination` | Page controls (prev/next/page numbers) |
| `OtpInputWidget` | 6-digit OTP input with auto-focus |
| `PasswordField` | TextField with visibility toggle |
| `CountryStatePicker` | Country + State dropdown with search |
| `ProfileImageWidget` | Circle avatar with upload/remove |

### AppButton Example
```dart
class AppButton extends StatelessWidget {
  const AppButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.isLoading = false,
    this.isOutlined = false,
    this.isFullWidth = true,
    this.icon,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool isLoading;
  final bool isOutlined;
  final bool isFullWidth;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final button = isOutlined
        ? OutlinedButton(
            onPressed: isLoading ? null : onPressed,
            child: _buildChild(),
          )
        : ElevatedButton(
            onPressed: isLoading ? null : onPressed,
            child: _buildChild(),
          );

    return isFullWidth ? SizedBox(width: double.infinity, child: button) : button;
  }

  Widget _buildChild() {
    if (isLoading) return const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2));
    if (icon != null) return Row(mainAxisSize: MainAxisSize.min, children: [Icon(icon), const SizedBox(width: 8), Text(label)]);
    return Text(label);
  }
}
```

---

## Layout System

### Auth Layout (Shell)
```dart
// Simple centered layout for login, register, forgot password
class AuthLayout extends StatelessWidget {
  const AuthLayout({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('App Name'),
        actions: [
          // Theme toggle button
        ],
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 480),
            child: child,
          ),
        ),
      ),
    );
  }
}
```

### User Layout (Shell with Drawer)
```dart
// Drawer + AppBar layout for user panel
class UserLayout extends StatelessWidget {
  const UserLayout({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: // dynamic page title
        actions: [
          // Notification bell
          // Profile menu (dropdown with Profile, Password, Security, Logout)
          // Theme toggle
        ],
      ),
      drawer: const AppDrawer(), // Dynamic menu from routes
      body: child,
    );
  }
}
```

### Page Layout Patterns

**Filter + Table Page (e.g., Ticket List):**
```dart
AppPageLayout(
  title: 'Support Tickets',
  filters: [
    // Search field, status dropdown, etc.
  ],
  actions: [
    // Compose button
  ],
  child: Column(children: [
    // Data table or ListView
    // Pagination controls
  ]),
)
```

**Form Page (e.g., Profile Edit):**
```dart
AppFormCard(
  title: 'Edit Profile',
  child: Form(
    key: _formKey,
    child: Column(children: [
      // Form fields
      // Save button
    ]),
  ),
)
```

---

## Data Models (freezed)

### Model Template
```dart
// lib/models/user_profile.dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'user_profile.freezed.dart';
part 'user_profile.g.dart';

@freezed
class UserProfile with _$UserProfile {
  const factory UserProfile({
    required String userId,
    required String firstName,
    required String lastName,
    String? email,
    String? mobile,
    String? country,
    String? state,
    String? profileImage,
    String? referralId,
    String? joiningDate,
  }) = _UserProfile;

  factory UserProfile.fromJson(Map<String, dynamic> json) => _$UserProfileFromJson(json);
}
```

### Schema (Request/Response DTO) Template
```dart
// lib/schemas/auth_schema.dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'auth_schema.freezed.dart';
part 'auth_schema.g.dart';

@freezed
class LoginRequest with _$LoginRequest {
  const factory LoginRequest({
    required String identifier,
    required String password,
    String? twoFactorCode,
    String? captchaToken,
  }) = _LoginRequest;

  factory LoginRequest.fromJson(Map<String, dynamic> json) => _$LoginRequestFromJson(json);
}

@freezed
class LoginResponse with _$LoginResponse {
  const factory LoginResponse({
    required String token,
    required String userId,
    required String role,
    String? accessRights,
    bool? requires2fa,
    List<String>? availableMethods,
    String? preferredMethod,
  }) = _LoginResponse;

  factory LoginResponse.fromJson(Map<String, dynamic> json) => _$LoginResponseFromJson(json);
}
```

---

## Action Verification — Reusable 2FA Interceptor (Critical Pattern)

This is the **most important architectural pattern** in the app. It makes 2FA verification automatic and transparent — no screen/page needs to implement 2FA logic individually.

### How It Works (Exact Flow)

```
1. Any screen makes an API call (e.g., update profile, disable 2FA)
2. API returns 403 + error_code: "2FA_REQUIRED"
3. Dio interceptor catches this response
4. Interceptor opens a modal dialog (ActionVerifyDialog)
5. User enters 6-digit 2FA code
6. Dialog calls /action-verify API → gets action_token
7. Interceptor retries the ORIGINAL request with X-Action-Token header
8. API accepts and processes the request
9. Calling screen receives success response (never knew about 2FA)
```

### Implementation in Dio Interceptor
```dart
// lib/core/network/action_verify_interceptor.dart
class ActionVerifyInterceptor extends Interceptor {
  ActionVerifyInterceptor(this._actionVerifyService);
  final ActionVerifyService _actionVerifyService;

  static const actionTokenHeader = 'X-Action-Token';
  static const action2faErrorCode = '2FA_REQUIRED';

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    if (err.response?.statusCode == 403) {
      final errorCode = err.response?.data?['error_code'];
      if (errorCode == action2faErrorCode) {
        // Show 2FA dialog and get action token
        final actionToken = await _actionVerifyService.getActionToken();
        
        if (actionToken != null) {
          // Retry original request with action token header
          final retryOptions = err.requestOptions;
          retryOptions.headers[actionTokenHeader] = actionToken;
          
          try {
            final response = await _actionVerifyService.dio.fetch(retryOptions);
            return handler.resolve(response);
          } catch (e) {
            return handler.reject(DioException(requestOptions: retryOptions, error: e));
          }
        } else {
          // User cancelled — reject with original error
          return handler.reject(err);
        }
      }
    }
    handler.next(err);
  }
}
```

### ActionVerifyService
```dart
// lib/core/services/action_verify_service.dart
class ActionVerifyService {
  final Dio dio;
  final GlobalKey<NavigatorState> navigatorKey; // For showing dialog from service

  /// Shows 2FA dialog and returns action token, or null if cancelled
  Future<String?> getActionToken() async {
    // 1. Fetch user's 2FA status (available methods)
    // 2. Show ActionVerifyDialog (modal, non-dismissable)
    // 3. Dialog handles: method selection, OTP sending, code entry, verification
    // 4. On success: returns action_token string
    // 5. On cancel: returns null
  }
}
```

### ActionVerifyDialog Widget
```dart
// lib/shared/widgets/action_verify_dialog.dart
// Modal dialog that:
// - Shows available 2FA methods (authenticator, email, SMS)
// - Sends OTP for email/SMS methods
// - Accepts 6-digit code via OtpInputWidget
// - Verifies code via /action-verify API
// - Returns action_token on success
// - Non-dismissable (user must complete or cancel)
// - "Try another way" to switch methods
// - Resend OTP with 30-second cooldown
```

### Why This Matters
- The API controls WHICH actions need 2FA (not the frontend)
- Adding 2FA to a new endpoint requires ZERO frontend changes
- Every API call automatically gets 2FA protection when the backend requires it
- The calling code is completely unaware of the 2FA flow

---

## CAPTCHA System — 3 Types, API-Controlled

The backend controls CAPTCHA configuration (enable/disable, type). The Flutter app must support all 3 types and render the correct one based on API response.

### Supported Types
| Type | UI | Token Source |
|------|-----|-------------|
| `image` | Server-generated image + text input field | Server token + user answer |
| `recaptcha_v2` | Google "I'm not a robot" checkbox widget | Google token |
| `recaptcha_v3` | Invisible (no UI), score-based | Google token (auto-executed) |

### Flow
```
1. Login/Register screen loads → calls GET /auth/captcha
2. API returns: { type: "image"|"recaptcha_v2"|"recaptcha_v3", image?, token?, site_key? }
3. CaptchaWidget renders correct UI based on type
4. On form submit: CaptchaWidget.execute() returns captcha_token
5. For image type: also sends captcha_answer (what user typed)
6. Payload includes captcha_token (+ captcha_answer for image)
```

### CaptchaWidget Pattern
```dart
// lib/shared/widgets/captcha_widget.dart
class CaptchaWidget extends ConsumerStatefulWidget {
  const CaptchaWidget({super.key, required this.onTokenChanged, required this.onTypeChanged});
  final ValueChanged<String?> onTokenChanged;
  final ValueChanged<String?> onTypeChanged;

  // Public method for parent to call on form submit
  Future<CaptchaResult> execute();
  
  // Public method to refresh/reload captcha
  void refresh();
}

class CaptchaResult {
  final String? token;
  final String? answer; // Only for image type
}
```

### Integration in Forms
```dart
// In login/register screen:
final _captchaKey = GlobalKey<CaptchaWidgetState>();

// In build:
CaptchaWidget(
  key: _captchaKey,
  onTokenChanged: (token) => _captchaToken = token,
  onTypeChanged: (type) => _captchaType = type,
)

// On submit:
Future<void> _handleSubmit() async {
  if (!_formKey.currentState!.validate()) return;
  
  CaptchaResult? captchaResult;
  if (_captchaType != null) {
    captchaResult = await _captchaKey.currentState!.execute();
  }
  
  final request = LoginRequest(
    identifier: _identifierController.text,
    password: _passwordController.text,
    captchaToken: captchaResult?.token,
    captchaAnswer: captchaResult?.answer,
  );
  // ... call API
}
```

### reCAPTCHA in Flutter
- For reCAPTCHA v2/v3 in Flutter, use `webview_flutter` or a package like `flutter_recaptcha_v2` / `g_recaptcha_v3`
- Image CAPTCHA: display base64 image via `Image.memory(base64Decode(imageData))`
- CAPTCHA type can change without app update (backend controls it)

---

## Security Patterns

### Token Storage
```dart
// Use flutter_secure_storage for JWT token
// Use shared_preferences for non-sensitive data (theme, preferences)

class AuthService {
  final FlutterSecureStorage _secureStorage;
  
  Future<void> saveToken(String token) async {
    await _secureStorage.write(key: 'auth_token', value: token);
  }
  
  Future<String?> get token async {
    return _secureStorage.read(key: 'auth_token');
  }
  
  Future<void> clearToken() async {
    await _secureStorage.delete(key: 'auth_token');
  }
}
```

### Input Validation
- All user input validated via `Validators` class
- Server-side validation errors displayed from API response
- XSS prevention: Flutter handles this natively (no raw HTML rendering)

### Route Protection
- GoRouter redirect guards check auth state
- Role-based access via access rights string
- Sensitive actions protected by Action Verification interceptor (automatic 2FA)

---

## Accessibility

- All interactive widgets must be focusable
- Icons must have `semanticLabel`
- Images must have `semanticsLabel`
- Touch targets minimum 48x48
- Sufficient color contrast (Material 3 handles this)
- Form fields have proper labels
- Error messages are descriptive

---

## Performance

- **Lazy loading:** Routes load screens on demand (GoRouter handles this)
- **Const widgets:** Use `const` wherever possible to prevent rebuilds
- **Provider disposal:** Use `autoDispose` for providers not needed globally
- **Image caching:** Use `cached_network_image` for all network images
- **List optimization:** Use `ListView.builder` for long lists (never `ListView` with all children)
- **Avoid rebuilds:** Use `select` on providers to watch specific fields
- **Keys:** Use proper keys for list items to optimize diffing

```dart
// GOOD — select specific field
final userName = ref.watch(authNotifierProvider.select((s) => s.userId));

// BAD — rebuilds on any auth state change
final authState = ref.watch(authNotifierProvider);
```

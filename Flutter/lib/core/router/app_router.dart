import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:template_app/core/constants/app_routes.dart';
import 'package:template_app/features/auth/screens/email_verification_notice_screen.dart';
import 'package:template_app/features/auth/screens/forgot_password_screen.dart';
import 'package:template_app/features/auth/screens/login_screen.dart';
import 'package:template_app/features/auth/screens/register_screen.dart';
import 'package:template_app/features/auth/screens/reset_password_screen.dart';
import 'package:template_app/features/auth/screens/two_factor_screen.dart';
import 'package:template_app/features/auth/screens/verify_email_screen.dart';
import 'package:template_app/features/user/screens/change_password_screen.dart';
import 'package:template_app/features/user/screens/compose_ticket_screen.dart';
import 'package:template_app/features/user/screens/dashboard_screen.dart';
import 'package:template_app/features/user/screens/login_history_screen.dart';
import 'package:template_app/features/user/screens/profile_screen.dart';
import 'package:template_app/features/user/screens/security_screen.dart';
import 'package:template_app/features/user/screens/ticket_list_screen.dart';
import 'package:template_app/features/user/screens/view_ticket_screen.dart';
import 'package:template_app/providers/auth_provider.dart';
import 'package:template_app/shared/layouts/auth_layout.dart';
import 'package:template_app/shared/layouts/user_layout.dart';

/// Creates the application [GoRouter] with auth guard redirects.
GoRouter createAppRouter(
  Ref ref, {
  GlobalKey<NavigatorState>? navigatorKey,
}) {
  return GoRouter(
    navigatorKey: navigatorKey,
    initialLocation: AppRoutes.pathLogin,
    redirect: (context, state) => _globalRedirect(state, ref),
    routes: [
      // ── Auth Routes (with AuthLayout shell) ────────────────────────
      ShellRoute(
        builder: (_, _, child) => AuthLayout(child: child),
        routes: [
          GoRoute(
            name: AppRoutes.login,
            path: AppRoutes.pathLogin,
            builder: (_, _) => const LoginScreen(),
          ),
          GoRoute(
            name: AppRoutes.register,
            path: AppRoutes.pathRegister,
            builder: (_, _) => const RegisterScreen(),
          ),
          GoRoute(
            name: AppRoutes.forgotPassword,
            path: AppRoutes.pathForgotPassword,
            builder: (_, _) => const ForgotPasswordScreen(),
          ),
          GoRoute(
            name: AppRoutes.resetPassword,
            path: AppRoutes.pathResetPassword,
            builder: (_, state) => ResetPasswordScreen(
              token: state.uri.queryParameters['token'],
            ),
          ),
          GoRoute(
            name: AppRoutes.twoFactorAuthentication,
            path: AppRoutes.pathTwoFactor,
            builder: (_, state) => TwoFactorScreen(
              extra: state.extra as Map<String, dynamic>?,
            ),
          ),
          GoRoute(
            name: AppRoutes.verifyEmail,
            path: AppRoutes.pathVerifyEmail,
            builder: (_, state) => VerifyEmailScreen(
              token: state.uri.queryParameters['token'],
            ),
          ),
          GoRoute(
            name: AppRoutes.emailVerificationNotice,
            path: AppRoutes.pathEmailVerificationNotice,
            builder: (_, state) => EmailVerificationNoticeScreen(
              extra: state.extra as Map<String, dynamic>?,
            ),
          ),
        ],
      ),

      // ── User Routes (with UserLayout shell) ────────────────────────
      ShellRoute(
        builder: (_, _, child) => UserLayout(child: child),
        routes: [
          GoRoute(
            name: AppRoutes.userDashboard,
            path: AppRoutes.pathDashboard,
            builder: (_, _) => const DashboardScreen(),
          ),
          GoRoute(
            name: AppRoutes.userProfile,
            path: AppRoutes.pathProfile,
            builder: (_, _) => const ProfileScreen(),
          ),
          GoRoute(
            name: AppRoutes.userSecurity,
            path: AppRoutes.pathSecurity,
            builder: (_, _) => const SecurityScreen(),
          ),
          GoRoute(
            name: AppRoutes.userChangePassword,
            path: AppRoutes.pathChangePassword,
            builder: (_, _) => const ChangePasswordScreen(),
          ),
          GoRoute(
            name: AppRoutes.userLoginHistory,
            path: AppRoutes.pathLoginHistory,
            builder: (_, _) => const LoginHistoryScreen(),
          ),
          GoRoute(
            name: AppRoutes.userSupport,
            path: AppRoutes.pathSupport,
            builder: (_, _) => const TicketListScreen(),
          ),
          GoRoute(
            name: AppRoutes.userTicketCompose,
            path: AppRoutes.pathTicketCompose,
            builder: (_, _) => const ComposeTicketScreen(),
          ),
          GoRoute(
            name: AppRoutes.userTicketView,
            path: AppRoutes.pathTicketView,
            builder: (_, _) => const ViewTicketScreen(),
          ),
        ],
      ),
    ],
  );
}

/// Auth guard — redirects based on authentication state.
String? _globalRedirect(GoRouterState state, Ref ref) {
  final authState = ref.read(authProvider);
  final isLoggedIn = authState.isAuthenticated;
  final currentPath = state.matchedLocation;

  const authPaths = {
    AppRoutes.pathLogin,
    AppRoutes.pathRegister,
    AppRoutes.pathForgotPassword,
    AppRoutes.pathResetPassword,
    AppRoutes.pathTwoFactor,
    AppRoutes.pathVerifyEmail,
    AppRoutes.pathEmailVerificationNotice,
  };

  final isAuthRoute = authPaths.contains(currentPath);

  // Unauthenticated user trying to access protected route → login
  if (!isLoggedIn && !isAuthRoute) {
    return AppRoutes.pathLogin;
  }

  // Authenticated user trying to access auth route → dashboard
  if (isLoggedIn && isAuthRoute) {
    return AppRoutes.pathDashboard;
  }

  return null;
}

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../core/constants/api_endpoints.dart';
import '../../core/theme/app_dimensions.dart';
import '../../providers/service_providers.dart';

/// Result returned by [CaptchaWidgetState.execute].
class CaptchaResult {
  const CaptchaResult({this.token, this.answer});

  /// Server token (image type) or Google token (reCAPTCHA types).
  final String? token;

  /// User's text answer — only populated for image type.
  final String? answer;
}

/// Supported CAPTCHA types — matches backend `CaptchaType`.
enum CaptchaType { image, recaptchaV2, recaptchaV3 }

CaptchaType? _parseCaptchaType(String? type) {
  switch (type) {
    case 'image':
      return CaptchaType.image;
    case 'recaptcha_v2':
      return CaptchaType.recaptchaV2;
    case 'recaptcha_v3':
      return CaptchaType.recaptchaV3;
    default:
      return null;
  }
}

/// API-controlled CAPTCHA widget supporting image, reCAPTCHA v2, and reCAPTCHA v3.
///
/// On init, calls `GET /auth/captcha` to determine the active type.
/// Use a [GlobalKey<CaptchaWidgetState>] to call [execute] and [refresh].
class CaptchaWidget extends ConsumerStatefulWidget {
  const CaptchaWidget({
    super.key,
    required this.onTokenChanged,
    required this.onTypeChanged,
  });

  final ValueChanged<String?> onTokenChanged;
  final ValueChanged<String?> onTypeChanged;

  @override
  ConsumerState<CaptchaWidget> createState() => CaptchaWidgetState();
}

class CaptchaWidgetState extends ConsumerState<CaptchaWidget> {
  CaptchaType? _captchaType;
  String _captchaImage = '';
  String _captchaToken = '';
  String _siteKey = '';
  bool _isLoading = false;

  final TextEditingController _answerController = TextEditingController();
  WebViewController? _webViewController;

  @override
  void initState() {
    super.initState();
    _loadCaptcha();
  }

  @override
  void dispose() {
    _answerController.dispose();
    super.dispose();
  }

  // ── Public API ──────────────────────────────────────────────────────

  /// Returns the current captcha token (and answer for image type).
  /// For reCAPTCHA v3, re-executes to get a fresh token.
  Future<CaptchaResult> execute() async {
    if (_captchaType == CaptchaType.recaptchaV3) {
      await _executeRecaptchaV3();
    }
    return CaptchaResult(
      token: _captchaToken,
      answer:
          _captchaType == CaptchaType.image ? _answerController.text : null,
    );
  }

  /// Refreshes the captcha — reloads image or resets reCAPTCHA.
  void refresh() {
    if (_captchaType == CaptchaType.recaptchaV2) {
      _resetRecaptchaV2();
    } else if (_captchaType == CaptchaType.recaptchaV3) {
      _executeRecaptchaV3();
    } else {
      _loadCaptcha();
    }
  }

  // ── Load from API ───────────────────────────────────────────────────

  Future<void> _loadCaptcha() async {
    setState(() => _isLoading = true);
    try {
      final apiHelper = ref.read(apiHelperProvider);
      final response = await apiHelper.get(ApiEndpoints.captcha);
      if (response.success && response.data != null) {
        final data = response.data as Map<String, dynamic>;
        final type = _parseCaptchaType(data['type'] as String?);
        _siteKey = data['site_key'] as String? ?? '';

        setState(() {
          _captchaType = type;
        });
        widget.onTypeChanged(data['type'] as String?);

        if (type == CaptchaType.image) {
          setState(() {
            _captchaImage = data['image'] as String? ?? '';
            _captchaToken = data['token'] as String? ?? '';
          });
          widget.onTokenChanged(_captchaToken);
          _answerController.clear();
        } else if (type == CaptchaType.recaptchaV2) {
          _initRecaptchaV2();
        } else if (type == CaptchaType.recaptchaV3) {
          _initRecaptchaV3();
        }
      } else {
        // Captcha disabled — render nothing
        setState(() => _captchaType = null);
        widget.onTypeChanged(null);
      }
    } catch (_) {
      // On error, treat as disabled
      setState(() => _captchaType = null);
      widget.onTypeChanged(null);
    } finally {
      setState(() => _isLoading = false);
    }
  }

  // ── Image CAPTCHA ───────────────────────────────────────────────────

  Widget _buildImageCaptcha(ThemeData theme) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppDimensions.md,
        vertical: AppDimensions.sm,
      ),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(AppDimensions.radiusMd),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      child: Row(
        children: [
          // Image + refresh button
          if (_captchaImage.isNotEmpty)
            ClipRRect(
              borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
              child: Image.memory(
                base64Decode(_captchaImage),
                height: 46,
                fit: BoxFit.contain,
              ),
            ),
          IconButton(
            onPressed: refresh,
            icon: const Icon(Icons.refresh, size: 20),
            tooltip: 'Refresh captcha',
            style: IconButton.styleFrom(
              foregroundColor: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(width: AppDimensions.sm),
          // Answer input
          Expanded(
            child: SizedBox(
              height: 40,
              child: TextField(
                controller: _answerController,
                decoration: InputDecoration(
                  hintText: 'Enter code',
                  isDense: true,
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: AppDimensions.md,
                    vertical: AppDimensions.sm,
                  ),
                  border: OutlineInputBorder(
                    borderRadius:
                        BorderRadius.circular(AppDimensions.radiusSm),
                  ),
                ),
                style: TextStyle(
                  fontFamily: 'monospace',
                  letterSpacing: 3,
                  fontSize: theme.textTheme.bodyLarge?.fontSize,
                ),
                textCapitalization: TextCapitalization.characters,
                autocorrect: false,
                enableSuggestions: false,
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ── reCAPTCHA v2 (checkbox via WebView) ─────────────────────────────

  void _initRecaptchaV2() {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final themeParam = isDark ? 'dark' : 'light';

    final html = '''
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://www.google.com/recaptcha/api.js?render=explicit" async defer></script>
  <style>
    body { margin: 0; padding: 0; display: flex; justify-content: center; align-items: center; min-height: 78px; background: transparent; }
  </style>
</head>
<body>
  <div id="recaptcha"></div>
  <script>
    function onRecaptchaLoad() {
      grecaptcha.render('recaptcha', {
        sitekey: '$_siteKey',
        theme: '$themeParam',
        callback: function(token) { Captcha.postMessage(token); },
        'expired-callback': function() { Captcha.postMessage(''); }
      });
    }
    var checkReady = setInterval(function() {
      if (typeof grecaptcha !== 'undefined' && grecaptcha.render) {
        clearInterval(checkReady);
        onRecaptchaLoad();
      }
    }, 100);
  </script>
</body>
</html>
''';

    _webViewController = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Colors.transparent)
      ..addJavaScriptChannel(
        'Captcha',
        onMessageReceived: (JavaScriptMessage message) {
          setState(() => _captchaToken = message.message);
          widget.onTokenChanged(
              message.message.isNotEmpty ? message.message : null);
        },
      )
      ..loadHtmlString(html);

    setState(() {});
  }

  void _resetRecaptchaV2() {
    _captchaToken = '';
    widget.onTokenChanged(null);
    _initRecaptchaV2();
  }

  Widget _buildRecaptchaV2() {
    if (_webViewController == null) {
      return const SizedBox.shrink();
    }
    return SizedBox(
      height: 78,
      child: WebViewWidget(controller: _webViewController!),
    );
  }

  // ── reCAPTCHA v3 (invisible via WebView) ────────────────────────────

  void _initRecaptchaV3() {
    final html = '''
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://www.google.com/recaptcha/api.js?render=$_siteKey"></script>
  <style>
    body { margin: 0; padding: 0; background: transparent; }
    .grecaptcha-badge { visibility: hidden; }
  </style>
</head>
<body>
  <script>
    function executeV3() {
      grecaptcha.ready(function() {
        grecaptcha.execute('$_siteKey', { action: 'submit' }).then(function(token) {
          Captcha.postMessage(token);
        }).catch(function() {
          Captcha.postMessage('');
        });
      });
    }
    var checkReady = setInterval(function() {
      if (typeof grecaptcha !== 'undefined' && grecaptcha.ready) {
        clearInterval(checkReady);
        executeV3();
      }
    }, 100);
  </script>
</body>
</html>
''';

    _webViewController = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Colors.transparent)
      ..addJavaScriptChannel(
        'Captcha',
        onMessageReceived: (JavaScriptMessage message) {
          setState(() => _captchaToken = message.message);
          widget.onTokenChanged(
              message.message.isNotEmpty ? message.message : null);
        },
      )
      ..loadHtmlString(html);

    setState(() {});
  }

  Future<void> _executeRecaptchaV3() async {
    if (_webViewController == null) return;
    await _webViewController!.runJavaScript('executeV3();');
    // Brief delay to allow the JS callback to fire
    await Future<void>.delayed(const Duration(milliseconds: 500));
  }

  // ── Build ───────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    // Captcha disabled — render nothing
    if (_captchaType == null && !_isLoading) {
      return const SizedBox.shrink();
    }

    if (_isLoading) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: AppDimensions.md),
        child: Center(
          child: SizedBox(
            height: 24,
            width: 24,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ),
      );
    }

    switch (_captchaType!) {
      case CaptchaType.image:
        return _buildImageCaptcha(theme);
      case CaptchaType.recaptchaV2:
        return _buildRecaptchaV2();
      case CaptchaType.recaptchaV3:
        // Invisible — no UI, but keep WebView in tree (zero height)
        if (_webViewController != null) {
          return SizedBox(
            height: 0,
            child: WebViewWidget(controller: _webViewController!),
          );
        }
        return const SizedBox.shrink();
    }
  }
}

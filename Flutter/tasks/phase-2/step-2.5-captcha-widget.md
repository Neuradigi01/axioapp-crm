# Step 2.5 — CAPTCHA Widget (3 Types: Image, reCAPTCHA v2, reCAPTCHA v3)

> **Status:** COMPLETED

> **Phase 2: Shared Widgets & Layouts**
> Read `Flutter/docs/COMPONENT_REFERENCE.md` — "CAPTCHA System" section.

**Prerequisites:** Step 2.4

---

**What to do:**
1. Create `lib/shared/widgets/captcha_widget.dart` — supports all 3 CAPTCHA types, API-controlled

**CAPTCHA types (backend decides which one is active):**
- **`image`** — Server-generated image (base64) + text input for answer + refresh button
- **`recaptcha_v2`** — Google "I'm not a robot" checkbox (use WebView or flutter package)
- **`recaptcha_v3`** — Invisible, score-based (auto-executes, no visible UI)

**CaptchaWidget behavior:**
1. On init: calls `GET /auth/captcha` to get current captcha config
2. API returns `{ type, image?, token?, site_key? }`
3. If `type == 'image'`: show base64 image + text input + refresh icon
4. If `type == 'recaptcha_v2'`: render Google reCAPTCHA v2 checkbox widget
5. If `type == 'recaptcha_v3'`: nothing visible (executes on demand)
6. If captcha is disabled (no response): render nothing

**Public API:**
- `execute()` → `Future<CaptchaResult>` — returns token (+ answer for image type)
- `refresh()` — reloads image or resets reCAPTCHA
- `onTokenChanged` callback
- `onTypeChanged` callback

**CaptchaResult:**
- `token` — captcha token (server token for image, Google token for reCAPTCHA)
- `answer` — user's text answer (only for image type, null otherwise)

**Dependencies:** May need `webview_flutter` or `flutter_recaptcha_v2` package for reCAPTCHA v2. For reCAPTCHA v3, use `g_recaptcha_v3` or WebView approach.

**Verify:**
- [ ] Image CAPTCHA displays base64 image with text input
- [ ] Refresh button reloads image CAPTCHA
- [ ] reCAPTCHA v2 renders checkbox widget
- [ ] reCAPTCHA v3 executes invisibly
- [ ] `execute()` returns correct token for each type
- [ ] Widget handles "captcha disabled" gracefully (renders nothing)
- [ ] Works in both light and dark theme

---

## Completion

This step is already completed. No action needed.



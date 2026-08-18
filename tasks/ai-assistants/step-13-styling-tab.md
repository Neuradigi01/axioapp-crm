# Step 13 — Styling tab UI + live-preview binding

**Goal:** Ship the Styling tab. Theme mode, assistant shape, 8 colour tokens, header profile picture upload. All fields bind to `styling_config` JSONB; preview re-renders live. Colour inputs use a shared colour-picker component (or a small native picker + hex text input) matching existing patterns.
**Status:** Pending
**Depends on:** Step 7 (editor shell + form-state), Step 5 (`styling_config` column), Step 10 (file upload endpoint for profile picture).

---

## Scope

In-scope:

- `editor/tabs/styling-tab.component.ts/.html` — flesh out:
  - **Theme Mode** dropdown — Light / Dark. Default Light.
  - **Assistant Shape** dropdown — Circle / Square. Default Circle. Help text "Select shape of the assistant icon".
  - **8 colour inputs** in a 2-column grid, matching Pabbly screenshot order:
    - Assistant Background Color (default `#128C7E`)
    - Assistant Text Color (default `#FFFFFF`)
    - Background Color (default `#FFFFFF`)
    - WhatsApp Buttons Color (rename to "CTA Buttons Color" per branding memory; internal key stays `cta_buttons_color`) (default `#25D366`)
    - Primary Chat Bubble Background Color (default `#FEFEFE`)
    - Primary Chat Bubble Text Color (default `#1C252E`)
    - Footer Background Color (default `#FFFFFF`)
    - Footer Text Color (default `#637381`)
  - Each colour field = small colour swatch button + hex text input (client-side hex validation).
  - **Header Profile Picture** — file input (image only, < 2 MB). On upload, stores via a small dedicated endpoint `POST /ai-assistants/{id}/profile-picture` (backend piece below); on success saves the returned storage path to `styling_config.header_profile_picture_url`. Shows current image + Remove button.
  - Two-way binds to `form-state` under `styling_config.*`.
  - Preview pane re-renders with the new palette.
- **Backend endpoint** — `POST /ai-assistants/{id}/profile-picture` in `core/ai_assistants/router.py`:
  - `multipart/form-data` with `file: UploadFile`.
  - Validates: image MIME (`image/png`, `image/jpeg`, `image/webp`), size < 2 MB, magic-byte sniff (reject non-image).
  - Stores at `{org_id}/ai_assistants/{assistant_id}/profile/{ts}.{ext}` (versioned filename so replaces are cache-safe).
  - Updates `styling_config.header_profile_picture_url` = signed URL for serving (existing signed-url infrastructure — grep `signed_url` service).
  - Delete endpoint `DELETE /ai-assistants/{id}/profile-picture` clears the URL and removes the storage file.

Out of scope:
- Real widget rendering with the styling (Step 15 uses `styling_config` in the shipped widget).
- Advanced theming (custom CSS, fonts, animations) — deferred.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/styling-tab.component.ts` | **EDIT** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/styling-tab.component.html` | **EDIT** |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/color-input.component.ts` | **NEW** — reusable colour swatch + hex input |
| `APP/src/app/features/user/core/ai-assistants/editor/tabs/color-input.component.html` | **NEW** |
| `APP/src/app/features/user/core/ai-assistants/editor/preview/assistant-preview.component.ts` | **EDIT** — apply styling_config |
| `APP/src/app/features/user/core/ai-assistants/form-state.service.ts` | **EDIT** — extend types |
| `APP/src/app/features/user/core/ai-assistants/ai-assistants-api.service.ts` | **EDIT** — profile-picture endpoints |
| `API/src/app/core/ai_assistants/router.py` | **EDIT** — profile-picture endpoints |
| `API/src/app/core/ai_assistants/service.py` | **EDIT** — profile-picture methods |
| `API/tests/ai_assistants/test_profile_picture.py` | **NEW** |

**~10 files. ~450 lines.**

## Plan

1. Colour input component reusable across the 8 fields — small, keeps HTML tidy.
2. Grep for existing colour-picker components before adding a new one; if one exists, reuse.
3. Profile-picture endpoint reuses Step 10's `file_upload.py` helper for magic-byte sniff.
4. Signed URL for serving: `styling_config.header_profile_picture_url` stores a **signed URL** with 30-day expiry (widget uses it directly; refresh on save).
5. Preview reads styling_config and applies inline styles (safe — values are hex validated).
6. Prettier on all files.

## DB changes / migrations

None — `styling_config` JSONB from Step 5.

## Tests

- All 8 colour fields save + reload with defaults if not set.
- Hex validation rejects `#ZZZ` and accepts `#FFF` / `#FFFFFF` / `#FFFFFF80`.
- Preview background/text colours update immediately on change.
- Profile picture upload: valid PNG → URL saved + rendered; invalid (SVG rejected — SVG can contain script); oversized rejected; magic-byte mismatch rejected.
- Delete profile picture clears URL and file.
- Shape change updates preview icon.

## Smoke

```
1. Open Styling tab. Change Assistant Background to #FF0000. Preview header goes red.
2. Upload a small PNG for profile picture. Renders in preview header.
3. Save. Reload. Colours + picture persist.
4. Try uploading an SVG — rejected.
```

## Risks

- SVG rejection is important (SVG can carry `<script>`). Whitelist raster formats only.
- Signed URL 30-day expiry: needs refresh on edit — Save re-issues.

## Self-check (10 rules)

`APP/` + small `core/ai_assistants/` router edit. ✓ Rule 2: profile picture stored under `{org_id}/...`. ✓ N/A rest. ✓ 10 files / ~450 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 13 — Styling tab UI + live-preview binding
Files: 10
Verify: all 8 colours save + reload; profile picture upload works; SVG rejected;
        preview reflects styling live.
Tests: ~7 pytest + Angular cases.
Awaiting "proceed".
```

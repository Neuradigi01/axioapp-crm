# =============================================================================
# WhatsApp live send/receive test — Neuradigi CRM prod
# =============================================================================
# Purpose:
#   Prove the full WhatsApp Cloud API path works against production:
#     1. Meta Cloud API accepts a send from the sandbox test number
#     2. Client's reply webhooks back to crm-api.aixoapp.com
#     3. (optional) CRM outbound endpoint sends via stored integration
#
# Target sandbox number: +1 (555) 197-7279
# Target recipient:      +91 89563 46287 (client)
# API host:              https://crm-api.aixoapp.com
#
# Usage:
#   1. Fill in $WA_TOKEN below (generate from Meta App > WhatsApp > API Setup)
#   2. (Optional) Fill in $CRM_PASSWORD for Test 3
#   3. Add +918956346287 as a verified recipient in Meta's "To" list
#   4. From the API/ folder run: powershell -File ..\test-whatsapp-live.ps1
# =============================================================================

# --- CONFIG ------------------------------------------------------------------
$WA_TOKEN     = "PASTE_ACCESS_TOKEN_HERE"
$WA_PHONE_ID  = "1288598037670970"
$WA_WABA_ID   = "4488208858121223"
$WA_RECIPIENT = "918956346287"
$API_VERSION  = "v22.0"

$CRM_BASE     = "https://crm-api.aixoapp.com"
$WEBHOOK_PATH = "/api/v1/conversations/webhooks/whatsapp"
$VERIFY_TOKEN = "neura-verify-wa"

$CRM_EMAIL    = "ajaygogane224@gmail.com"
$CRM_PASSWORD = "PASTE_PASSWORD_HERE"
# -----------------------------------------------------------------------------

$ErrorActionPreference = "Continue"

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host ("=" * 76) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ("=" * 76) -ForegroundColor Cyan
}

function Invoke-Api {
    param(
        [string]$Method,
        [string]$Url,
        [hashtable]$Headers = @{},
        [string]$Body = $null
    )
    Write-Host ">>> $Method $Url" -ForegroundColor Gray
    if ($Body) { Write-Host ">>> $Body" -ForegroundColor DarkGray }
    try {
        $params = @{
            Method  = $Method
            Uri     = $Url
            Headers = $Headers
            ErrorAction = "Stop"
        }
        if ($Body) {
            $params["Body"] = $Body
            $params["ContentType"] = "application/json"
        }
        $r = Invoke-WebRequest @params
        Write-Host "<<< HTTP $($r.StatusCode)" -ForegroundColor Green
        Write-Host $r.Content
        return ($r.Content | ConvertFrom-Json -ErrorAction SilentlyContinue)
    } catch {
        $status = $null
        if ($_.Exception.Response) {
            $status = $_.Exception.Response.StatusCode.value__
            $stream = $_.Exception.Response.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($stream)
            $bodyText = $reader.ReadToEnd()
        } else {
            $bodyText = $_.Exception.Message
        }
        Write-Host "<<< HTTP $status" -ForegroundColor Red
        Write-Host $bodyText -ForegroundColor Red
        return $null
    }
}

if ($WA_TOKEN -eq "PASTE_ACCESS_TOKEN_HERE") {
    Write-Host "ABORT: fill in `$WA_TOKEN before running." -ForegroundColor Red
    Write-Host "  Meta App Dashboard > WhatsApp > API Setup > Step 1 > Generate token" -ForegroundColor Yellow
    exit 1
}

# =============================================================================
# TEST 0 — Webhook verify handshake (proves DB row + Cloudflare routing)
# =============================================================================
Write-Section "TEST 0 - Webhook verify handshake"

$verifyUrl = "$CRM_BASE$WEBHOOK_PATH" +
    "?hub.mode=subscribe" +
    "&hub.verify_token=$VERIFY_TOKEN" +
    "&hub.challenge=probe123"

$verifyResp = Invoke-Api -Method Get -Url $verifyUrl
if (-not $verifyResp) {
    # response body was "probe123" plain text, not JSON — fetch raw
    try {
        $r = Invoke-WebRequest -Method Get -Uri $verifyUrl -ErrorAction Stop
        if ($r.Content.Trim() -eq "probe123") {
            Write-Host "PASS: handshake returned 'probe123'" -ForegroundColor Green
        } else {
            Write-Host "FAIL: expected 'probe123', got '$($r.Content)'" -ForegroundColor Red
            exit 1
        }
    } catch {
        Write-Host "FAIL: verify_token '$VERIFY_TOKEN' does not match DB row." -ForegroundColor Red
        Write-Host "→ Check tbl_whatsapp_account_configs.verify_token in prod." -ForegroundColor Yellow
        exit 1
    }
}

# =============================================================================
# TEST 1 — Send hello_world template (opens the 24-hour window)
# =============================================================================
Write-Section "TEST 1 - Send hello_world template to +$WA_RECIPIENT"

$sendUrl = "https://graph.facebook.com/$API_VERSION/$WA_PHONE_ID/messages"
$sendHeaders = @{ "Authorization" = "Bearer $WA_TOKEN" }

$templateBody = @{
    messaging_product = "whatsapp"
    to                = $WA_RECIPIENT
    type              = "template"
    template          = @{
        name     = "hello_world"
        language = @{ code = "en_US" }
    }
} | ConvertTo-Json -Depth 5 -Compress

$sendResult = Invoke-Api -Method Post -Url $sendUrl -Headers $sendHeaders -Body $templateBody

if ($sendResult -and $sendResult.messages) {
    Write-Host ""
    Write-Host "PASS: Meta accepted the send." -ForegroundColor Green
    Write-Host "wamid: $($sendResult.messages[0].id)" -ForegroundColor Green
    Write-Host "→ Client should see 'Hello World' from +1 555-197-7279 within ~5s" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "FAIL: send rejected. Common causes:" -ForegroundColor Red
    Write-Host "  - 401 OAuthException      → access token expired / wrong app" -ForegroundColor Yellow
    Write-Host "  - 131047 (or 470)         → recipient not on Meta 'To' allowlist" -ForegroundColor Yellow
    Write-Host "  - 132001 template missing → try language.code = 'en' instead" -ForegroundColor Yellow
    Write-Host "  - 100 (Unsupported ...)   → recipient string must be E.164 without '+'" -ForegroundColor Yellow
    exit 1
}

# =============================================================================
# TEST 2 — Wait for inbound reply and verify the webhook path
# =============================================================================
Write-Section "TEST 2 - Wait for client to reply (opens 24h window)"

Write-Host "Ask the client to REPLY to the WhatsApp message from +1 555-197-7279." -ForegroundColor Yellow
Write-Host ""
Write-Host "On the PROD HOST tail the logs while they reply:" -ForegroundColor Yellow
Write-Host "  docker logs -f crm-api-1 2>&1 | Select-String 'whatsapp|webhook|POST /api/v1/conversations'" -ForegroundColor Gray
Write-Host ""
Write-Host "You should see a line like:" -ForegroundColor Yellow
Write-Host '  POST /api/v1/conversations/webhooks/whatsapp HTTP/1.1" 202' -ForegroundColor Gray
Write-Host ""
Write-Host "Verify the message landed in the DB:" -ForegroundColor Yellow
Write-Host @'
  docker exec crm-api-1 python -c "import asyncio; from sqlalchemy import text; from src.app.shared.db import async_session
  async def r():
      async with async_session() as s:
          rows = (await s.execute(text(\"SELECT id, channel, body_text, from_phone, to_phone, created_at FROM tbl_messages WHERE channel='whatsapp' AND (from_phone LIKE '%918956346287%' OR to_phone LIKE '%918956346287%') ORDER BY created_at DESC LIMIT 5\"))).mappings().all()
          for x in rows: print(dict(x))
  asyncio.run(r())"
'@ -ForegroundColor Gray

Read-Host "`nPress ENTER once the client has replied (or to skip this test)"

# =============================================================================
# TEST 3 — Send freeform text (only works if 24h window is open)
# =============================================================================
Write-Section "TEST 3 - Send freeform text via Graph API"

$freeformBody = @{
    messaging_product = "whatsapp"
    to                = $WA_RECIPIENT
    type              = "text"
    text              = @{
        preview_url = $false
        body        = "Hi from Neuradigi CRM - this is a freeform test message (24h window)."
    }
} | ConvertTo-Json -Depth 5 -Compress

$ffResult = Invoke-Api -Method Post -Url $sendUrl -Headers $sendHeaders -Body $freeformBody

if ($ffResult -and $ffResult.messages) {
    Write-Host "PASS: freeform text delivered." -ForegroundColor Green
} elseif ($ffResult -and $ffResult.error) {
    if ($ffResult.error.code -eq 131047 -or $ffResult.error.code -eq 470) {
        Write-Host "24h window closed. Have the client reply, then re-run this test." -ForegroundColor Yellow
    }
}

# =============================================================================
# TEST 4 — Send through the CRM (proves outbound wiring end-to-end)
# =============================================================================
if ($CRM_PASSWORD -eq "PASTE_PASSWORD_HERE") {
    Write-Section "TEST 4 - Skipped (set `$CRM_PASSWORD to enable)"
    exit 0
}

Write-Section "TEST 4 - Send THROUGH the CRM (JWT auth)"

$loginBody = @{ email = $CRM_EMAIL; password = $CRM_PASSWORD } | ConvertTo-Json -Compress
$loginResp = Invoke-Api -Method Post -Url "$CRM_BASE/api/v1/auth/login" -Body $loginBody
if (-not $loginResp -or -not $loginResp.access_token) {
    Write-Host "FAIL: login failed. Check credentials." -ForegroundColor Red
    exit 1
}
$jwt = $loginResp.access_token
Write-Host "JWT acquired." -ForegroundColor Green

# Look up the contact by phone
$contactsResp = Invoke-Api -Method Get -Url "$CRM_BASE/api/v1/contacts?q=$WA_RECIPIENT" `
    -Headers @{ "Authorization" = "Bearer $jwt" }

$contact = $null
if ($contactsResp -and $contactsResp.items -and $contactsResp.items.Count -gt 0) {
    $contact = $contactsResp.items[0]
}
if (-not $contact) {
    Write-Host "No contact found for +$WA_RECIPIENT — create one in the CRM UI first, then re-run." -ForegroundColor Yellow
    exit 0
}
Write-Host "Contact ID: $($contact.id)" -ForegroundColor Green

# NOTE: adjust the endpoint/body if your CRM send route differs. This calls
# the conversations send endpoint used by the inbox UI.
$crmSendBody = @{
    contact_id = $contact.id
    channel    = "whatsapp"
    body_text  = "Test from CRM outbound path via /api/v1/conversations"
} | ConvertTo-Json -Compress

Invoke-Api -Method Post -Url "$CRM_BASE/api/v1/conversations" `
    -Headers @{ "Authorization" = "Bearer $jwt" } -Body $crmSendBody

Write-Host ""
Write-Host "DONE — check the WhatsApp thread on +$WA_RECIPIENT and the CRM Conversations UI." -ForegroundColor Green

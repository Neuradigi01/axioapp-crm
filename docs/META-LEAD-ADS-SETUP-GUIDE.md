# Meta Lead Ads Integration — Complete Setup Guide

End-to-end pipeline: FB ad form submit → webhook → backend → Celery worker → CRM lead arrival.

---

## Overview

Yeh integration **Facebook/Instagram Lead Ads** se aane wale leads **automatically CRM mein capture** karta hai. User FB pe ad dekhe, form fill kare → CRM `/user/leads` mein lead arrive ho jata hai with `source=meta_ads` badge.

### Pipeline flow

```
User submits FB Lead Form
       ↓
Meta sends leadgen webhook → ngrok → backend (HMAC verified)
       ↓
Backend enqueues Celery task (Redis broker)
       ↓
Worker picks up task → resolves page_id → org_id → subscription
       ↓
Calls Meta Graph API: GET /{leadgen_id}?fields=field_data
       ↓
Field mapping: form fields → CRM contact keys
       ↓
Create/dedup Contact + Create Lead with attribution
       ↓
Round-robin assigned to sales rep
       ↓
Lead visible in CRM /user/leads
```

---

## Prerequisites

- **Docker Desktop** chalu (Windows)
- **Python 3.13** local (optional — ngrok aur basic scripts ke liye)
- **Node.js 18+** + **npm** (frontend ke liye)
- **Facebook account** with admin rights on a FB Page
- **Meta Business Manager** account
- **ngrok** account (free tier OK)
- **sops + age** installed + your **age key** present (`run.cmd secrets-keygen` if first time on this machine) with your public key added as a recipient in `API/.sops.yaml`. Secrets then decrypt automatically — no MASTER_KEY. See [`API/SOPS_INTEGRATION_GUIDE.md`](API/SOPS_INTEGRATION_GUIDE.md).

---

## Project Structure Recap

```
crm/
├── API/                ← Backend (FastAPI + Python)
│   ├── docker-compose.yml
│   ├── docker-compose.dev.yml
│   ├── config.env        ← Non-secret config (committed, plaintext)
│   ├── secrets.enc.env   ← Secrets, SOPS + age encrypted (committed)
│   ├── run.cmd / run.sh  ← Stack runner (wraps `sops exec-env`)
│   ├── requirements.txt
│   └── src/
│       └── app/core/integrations/meta/   ← Meta integration code
│
└── APP/                ← Frontend (Angular)
    ├── package.json
    └── src/
```

---

## Phase 1 — ngrok HTTPS Tunnel Setup

Meta webhook localhost pe push nahi kar sakta — public HTTPS chahiye. ngrok aapke `localhost:8000` ko public URL bana deta hai.

### 1.1 Install ngrok

PowerShell:

```powershell
winget install ngrok.ngrok
```

### 1.2 ngrok authenticate

1. [ngrok.com/signup](https://ngrok.com/signup) — free account banao
2. [dashboard.ngrok.com/get-started/your-authtoken](https://dashboard.ngrok.com/get-started/your-authtoken) — authtoken copy karo
3. PowerShell:
   ```powershell
   ngrok config add-authtoken <YOUR_AUTHTOKEN>
   ```

### 1.3 Tunnel start karo

```powershell
ngrok http 8000
```

Output mein milega:
```
Forwarding   https://XXXX-31-97-109-228.ngrok-free.app -> http://localhost:8000
```

**Yeh URL note karo** — Phase 2 + 3 mein use hoga.

⚠️ **Critical**: Free tier mein har restart pe URL **change** hota hai. Iska matlab `config.env` aur Meta dashboard har baar update karne padenge. Production mein stable HTTPS chahiye (Cloudflare Tunnel free + static URL deta hai).

---

## Phase 2 — Meta App Creation

### 2.1 App banao

1. [developers.facebook.com/apps](https://developers.facebook.com/apps) kholo
2. **"Create App"** click karo
3. **Use case**: "Other" → Next
4. **App type**: **Business** → Next
5. App name: `Crm` (ya kuch bhi)
6. App contact email + Business Account select karo
7. **Create App**

### 2.2 App ID + Secret save karo

App Dashboard → **App settings → Basic**:
- **App ID** (top — long number)
- **App Secret** — "Show" button click karo, password confirm karo

**App ID** `config.env` mein jayega (non-secret); **App Secret** `secrets.enc.env` mein (secret) — Phase 3 dekho.

### 2.3 Use Case add karo — "Capture & manage ad leads with Marketing API"

1. Left sidebar: **Use cases** → **"Add use cases"** button (top right)
2. Search: **"Capture & manage ad leads with Marketing API"**
3. Select karo + **Save**
4. Wapas Use Cases page pe — naya card dikhega → **Customize** click

### 2.4 Permissions — "Ready for testing" status karo

**Permissions and Features** mein yeh 6 permissions check karo (sab "Ready for testing" hone chahiye):

| Permission | Status |
|-----------|--------|
| `pages_show_list` | Ready for testing ✅ |
| `pages_read_engagement` | Ready for testing ✅ |
| `pages_manage_metadata` | Ready for testing ✅ |
| `pages_manage_ads` | Ready for testing ✅ (critical — Meta v25+ requires this) |
| `leads_retrieval` | Ready for testing ✅ |
| `business_management` | Ready for testing ✅ |

Agar koi "Standard access" mein hai → **Actions → "Get advanced access"** click karo.

### 2.5 Facebook Login OAuth Redirect URI

Left sidebar: **Facebook Login for Business → Settings**

**Valid OAuth Redirect URIs** field mein add karo:

```
https://<YOUR_NGROK_URL>.ngrok-free.app/api/v1/integrations/meta/callback
```

Page bottom **Save changes**.

### 2.6 Webhook callback URL

Same Customize page → **Webhooks tab** → `Page` dropdown select karo

| Field | Value |
|-------|-------|
| Callback URL | `https://<YOUR_NGROK_URL>.ngrok-free.app/api/v1/integrations/meta/webhook` |
| Verify Token | Step 3.2 mein generate kiya hua (`META_WEBHOOK_VERIFY_TOKEN`) |

**"Verify and Save"** click karo → green tick ✅

### 2.7 `leadgen` field subscribe karo

Same page, scroll down → **Webhook fields** table → `leadgen` row mein **Subscribe** toggle ON karo.

---

## Phase 3 — `config.env` + `secrets.enc.env` Configuration

Non-secret values `config.env` mein (committed plaintext); secrets `secrets.enc.env` mein (SOPS-encrypted, committed).

### 3.1 Secrets edit kaise karein

```powershell
cd C:\Users\USER\Desktop\Projects\crm\API
run.cmd secrets-edit
```

Yeh `secrets.enc.env` ko aapke editor mein **decrypted** kholega; save karte hi **re-encrypt** ho jayega. `config.env` ek normal text editor se edit karo. `secrets.enc.env` ko **kabhi haath se edit mat karo** — sirf `run.cmd secrets-edit` se.

### 3.2 Verify Token generate karo

PowerShell:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Output (example): `mK7tQ9_rP3vYx2NbHl4Wj8sFcA6oZxKpRdEvL5T-uXg`

Yeh value **dono jagah** use hogi:
- `secrets.enc.env` mein (it's a secret)
- Meta dashboard webhook Verify Token field mein

### 3.3 Meta values fill karo

**Non-secret** → `config.env` (normal editor):

```ini
# Meta (Facebook + Instagram) Ads OAuth
META_APP_ID=<App_ID_from_2.2>
META_OAUTH_REDIRECT_URI=https://<YOUR_NGROK_URL>.ngrok-free.app/api/v1/integrations/meta/callback
META_GRAPH_API_VERSION=v19.0
```

**Secrets** → `run.cmd secrets-edit` (decrypts `secrets.enc.env`):

```ini
META_APP_SECRET=<App_Secret_from_2.2>
META_WEBHOOK_VERIFY_TOKEN=<token_from_3.2>
```

### 3.4 Celery enable karo

`config.env` mein:

```ini
CELERY_ENABLED=true
```

### 3.5 DB + other secrets

`DB_PASSWORD`, `JWT_SECRET_KEY`, `FERNET_KEY`, `INTEGRATIONS_ENCRYPTION_KEY` waance sab `secrets.enc.env` mein SOPS-encrypted hain. `run.cmd` har stack/DB command pe inhe **in-memory decrypt** karta hai (`sops exec-env`) aur containers mein forward karta hai — koi MASTER_KEY ya manual decrypt step nahi. Disk pe plaintext secrets kabhi nahi.

---

## Phase 4 — Lead Access Manager (Meta-side, CRITICAL)

Yeh step skip karoge toh Lead Ads Testing Tool webhook trigger nahi karega — sirf paid ads work karenge.

### 4.1 Business Settings kholo

```
https://business.facebook.com → Settings (gear icon)
```

### 4.2 Page add karo to Leads Access

Left sidebar (bottom): **Integrations → Leads access**

**+ Add** button → **"Add an existing Page"** wizard:
1. Search: "IPSC University Test" (ya aapki Page)
2. Next → Review people → Next
3. Request approval → **Add Page**

### 4.3 People assign karo

Page list mein Page click karo → **People tab** → **Assign people**:
- Khud ko select karo (Abhishek Pandey)
- **"Manage leads access"** toggle ON
- **Assign**

### 4.4 CRMs assign karo

Same Page detail → **CRMs tab** → **Assign CRM**:
- Search: `Crm` (App ID `<APP_ID>`)
- Select → Save

Ab Page ke liye Lead Access fully configured hai.

---

## Phase 5 — Docker Stack Setup

### 5.1 First time? sops + age + age key ready karo

```powershell
cd C:\Users\USER\Desktop\Projects\crm\API
run.cmd secrets-install     # sops + age install (winget) — phir NEW terminal kholo PATH refresh ke liye
run.cmd secrets-keygen      # is machine ki age key banao; aapki age1... PUBLIC key print karega
```

Apni **public** key `.sops.yaml` manage karne wale ko bhejo. Woh use add karke `run.cmd secrets-rekey` chalayega + `secrets.enc.env` commit karega. Uske baad aap decrypt kar paoge. (Agar key pehle se hai toh yeh skip.)

⚠️ Koi MASTER_KEY nahi — `run.cmd` har command pe `secrets.enc.env` ko aapki age key se **in-memory** decrypt karta hai. Private key (`%USERPROFILE%\.config\sops\age\keys.txt`) kabhi commit/share mat karo.

### 5.2 Docker stack up

```powershell
cd C:\Users\USER\Desktop\Projects\crm\API
run.cmd up
```

`run.cmd up` = full stack (api + redis + celery + beat + flower), secrets in-memory decrypt karke. 60 sec wait karo (alembic migrations + seeds + module discovery).

### 5.3 Status verify

```powershell
docker compose --env-file config.env -f docker-compose.yml -f docker-compose.dev.yml --profile celery ps
```

5 services `Up X seconds` hone chahiye:
- crm-api-1
- crm-celery-1
- crm-celery-beat-1
- crm-flower-1
- crm-redis-1

### 5.4 Health checks

```powershell
curl http://localhost:8000/api/v1/health
```

Expected: `{"status":"ok","version":"0.1.0"}`

```powershell
curl https://<YOUR_NGROK_URL>.ngrok-free.app/api/v1/health
```

Same response — confirms ngrok tunnel forwarding works.

### 5.5 Pool type verify (NullPool active)

```powershell
docker exec crm-celery-1 python -c "from src.core.db import engine; print('Pool:', type(engine.sync_engine.pool).__name__)"
```

Expected: `Pool: NullPool` ✅

(Agar `AsyncAdaptedQueuePool` aaye → `DB_NULL_POOL=1` env var ya volume mount missing hai docker-compose.dev.yml mein.)

---

## Phase 6 — Frontend + CRM OAuth Flow

### 6.1 Frontend start karo

Naya PowerShell:

```powershell
cd C:\Users\USER\Desktop\Projects\crm\APP
npm install
npm start
```

Browser: `http://localhost:4200`

### 6.2 Login

URL: `http://localhost:4200/accounts/login`

**User login** button click karo (NOT Admin login):
- Email: `neuradigi02@gmail.com` (ya aapka actual user email)
- Password: `Neuradigi@123`

### 6.3 Settings → Integrations

```
http://localhost:4200/user/settings/integrations
```

3 cards: Google Ads, Meta Ads, WhatsApp Business

### 6.4 Meta "Connect" click karo

Meta card pe **Connect** button click karo. FB OAuth consent screens aayenge:

1. **Choose Businesses**: "Opt in to all current and future Businesses"
2. **Choose Pages**: "Opt in to all current and future Pages"
3. **Permissions review** — sab 6 toggles ON:
   - Manage your business
   - Access leads for your Pages
   - Read content posted on the Page
   - **Create and manage ads for your Page** (critical!)
   - Manage accounts, settings and webhooks
   - Show a list of the Pages you manage
4. **Save**

Redirect ho jaoge `/user/settings/integrations?status=meta_connected` pe with green toast.

### 6.5 Page subscribe karo

Meta card mein **"Load"** click karo → Pages list aayegi → **"IPSC University Test"** ke side **Subscribe** button click karo.

API logs:
```
POST /api/v1/integrations/meta/pages/<page_id>/subscribe HTTP/1.1" 200 OK
```

---

## Phase 7 — Lead Form Create karo FB Page pe

### 7.1 Meta Business Suite kholo

```
https://business.facebook.com → Page select karo → All tools
```

### 7.2 Instant Forms

**Instant Forms** ya **Lead Center** dhundo → **Create Form** button.

### 7.3 Form configure

| Step | Field | Value |
|------|-------|-------|
| 1. Form type | Select | **More Volume** |
| 2. Intro | Headline | Kuch bhi (`"Get free quote"`) |
| 3. Questions | Prefill fields | ✅ Full Name, ✅ Email, ✅ Phone Number |
| 4. Privacy Policy | URL | `https://www.google.com/policies/privacy/` (test ke liye) |
| 5. Ending | Default | Skip / default |
| 6. Review | — | **Publish** click karo (NOT Save Draft) |

⚠️ **Form publish hone ke baad edit nahi hota** — fields lock ho jate hain.

### 7.4 Form ID note karo

CRM wapas → Meta card → Page expand (`>` chevron) → form row mein **form_id** dikhega (long number jaise `1626019278698746`).

---

## Phase 8 — Subscription + Field Mapping

⚠️ **Meta card UI mein per-form subscribe + mapping editor MISSING hai** (Google card mein hai). Workaround: API call se manually create karo.

### 8.1 JWT token nikalo

Browser pe CRM mein:
1. **F12** → Application tab
2. Left: Storage → Local Storage → `http://localhost:4200`
3. Key `access_token` ya `token` ka value copy karo

### 8.2 Integration ID nikalo (DevTools Console)

F12 → Console tab → `allow pasting` type karo + Enter (Chrome security):

```javascript
const token = localStorage.getItem('access_token') || localStorage.getItem('token'); fetch('http://localhost:8000/api/v1/integrations', {headers: {Authorization: 'Bearer ' + token}}).then(r=>r.json()).then(d=>{const meta=d.find(i=>i.provider==='meta_ads'); window.metaIntegrationId = meta.id; console.log('META INTEGRATION ID:', meta.id);});
```

Output: `META INTEGRATION ID: <UUID>` copy karo.

### 8.3 Subscription create karo

```javascript
fetch('http://localhost:8000/api/v1/integrations/subscriptions', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer ' + (localStorage.getItem('access_token') || localStorage.getItem('token')),
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    integration_id: window.metaIntegrationId,
    external_form_id: '<YOUR_FORM_ID>',
    external_form_label: 'My Lead Form',
    field_mapping: {
      'full_name': 'contact.full_name',
      'email': 'contact.email',
      'phone_number': 'contact.phone'
    },
    enabled: true
  })
}).then(r=>r.json()).then(d=>console.log('SUBSCRIPTION CREATED:', d));
```

Output: subscription object with `id`, `field_mapping`, `enabled: true`.

---

## Phase 9 — Testing the Pipeline

### Option A — Test webhook from Meta dashboard

Meta App Dashboard → Webhooks tab → `leadgen` row → **Test** button → **"Send to server v25.0"**

Meta synthetic payload bhejega with fake `page_id=444444444444`. Backend receive karega lekin DLQ mein land karega (fake page_id resolve nahi hota).

API logs:
```
POST /api/v1/integrations/meta/webhook HTTP/1.1" 200 OK
meta webhook: signature ok, enqueued 1 leadgen task(s)
```

Celery logs:
```
Task ...process_meta_lead[xxx] received
Task ... succeeded: {'status': 'dlq', 'reason': 'no_page_token'}
```

CRM Settings → "View DLQ" → naya Meta entry visible ✅

Yeh **pipeline plumbing prove** karta hai.

### Option B — Real lead via Lead Ads Testing Tool

```
https://developers.facebook.com/tools/lead-ads-testing
```

- Page: IPSC University Test
- Form: Aapka form
- **Page Diagnostics** ALL GREEN hone chahiye (Phase 4 ka Lead Access Manager configured ke saath)

**Delete lead** (purana stuck) → **Create lead** (auto-fills test data) → **Track status** → wait **"Success"**

Backend logs mein:
```
Task ...process_meta_lead[xxx] succeeded: {'status': 'created', 'lead_id': '<UUID>'}
```

CRM `/user/leads` → naya lead with **Source: Meta Ads** badge ✅

⚠️ **Note**: Meta Lead Ads Testing Tool sends **dummy placeholder data** (`<test lead: dummy data for X>`). Hamare code mein dummy detection fix hai jo inn placeholders ko gracefully skip karta hai — but lead minimal data ke saath create hoga (email present, name/phone defaults pe gir jayenge).

### Option C — Manual task fire with real leadgen_id

Agar Testing Tool stuck rahe ya manually verify karna ho:

#### C.1 Real leadgen_id pull karo

```powershell
docker exec crm-celery-1 python -c "import asyncio, httpx, asyncpg; from src.app.core.integrations.crypto import decrypt; from config import DB_PASSWORD, DB_HOST, DB_PORT, DB_USER, DB_NAME; loop = asyncio.new_event_loop(); c = loop.run_until_complete(asyncpg.connect(host=DB_HOST, port=int(DB_PORT), user=DB_USER, password=DB_PASSWORD, database=DB_NAME)); row = loop.run_until_complete(c.fetchrow(\"SELECT page_token_enc FROM meta_page_tokens WHERE page_id='<PAGE_ID>'\")); token = decrypt(row['page_token_enc']); loop.run_until_complete(c.close()); h = httpx.Client(); r = h.get('https://graph.facebook.com/v19.0/<FORM_ID>/leads', params={'access_token': token, 'limit': 50}); print(r.json())"
```

Output mein leads list → kisi entry ka `id` field copy karo.

#### C.2 Task fire karo

```powershell
docker exec crm-celery-1 python -c "from src.celery.worker import celery; from src.app.core.integrations.meta.tasks import process_meta_lead; result = process_meta_lead.delay({'leadgen_id': '<REAL_LEADGEN_ID>', 'form_id': '<FORM_ID>', 'page_id': '<PAGE_ID>', 'ad_id': None, 'campaign_id': None, 'created_time': 1780472068}); print('Task queued:', result.id)"
```

#### C.3 Logs check

```powershell
docker logs crm-celery-1 --since 30s 2>&1 | findstr /i "process_meta"
```

Expected: `succeeded: {'status': 'created', 'lead_id': '...'}`

#### C.4 CRM verify

```
http://localhost:4200/user/leads
```

F5 → naya lead with Meta Ads source ✅

### Option D — Paid Ad (production-grade test)

[adsmanager.facebook.com](https://adsmanager.facebook.com) → Create Ad with objective "Leads":
- Page: IPSC University Test
- Form: Aapka form
- Budget: ₹50-100, 1 day, broad targeting
- Publish

Real users form fill karenge → **real webhook fire** → CRM mein real leads arrive **within hours**.

---

## Troubleshooting — Common Issues

### Issue 1 — `ngrok 502 ERR_NGROK_3004` ya tunnel dead

ngrok terminal band ho gaya. Restart karo: `ngrok http 8000`. **Naya URL milega** — `config.env` aur Meta dashboard ke 2 URLs update karo.

### Issue 2 — `InvalidPasswordError` for postgres (ya secrets empty)

Secrets decrypt nahi ho rahe / inject nahi hue. Check:
1. `sops` + `age` installed hain (`run.cmd secrets-install`).
2. Aapki age key maujood hai (`%USERPROFILE%\.config\sops\age\keys.txt`) aur aapki public key `.sops.yaml` recipients mein hai (warna `run.cmd secrets-rekey` karwao).
3. Stack hamesha `run.cmd up` se chalao — raw `docker compose up` secrets ko inject **nahi** karta (empty values milenge).

### Issue 3 — `meta webhook: failed to enqueue task`

API container Celery app initialize nahi kar raha. Fix: `src/app/main.py` mein top-level import add:

```python
from src.celery.worker import celery as _celery_app  # noqa: F401
```

API restart karo.

### Issue 4 — `InterfaceError: cannot perform operation: another operation is in progress`

Celery worker mein async DB engine cross-loop bug. Fix:
1. `src/core/db.py` mein NullPool support (env var `DB_NULL_POOL`)
2. `docker-compose.dev.yml` mein celery/beat/flower services pe:
   - `DB_NULL_POOL=1` env var
   - `volumes: - .:/app` mount

Container recreate karo (`run.cmd restart`).

### Issue 5 — `NoReferencedTableError: organizations`

Celery worker process mein ORM models load nahi hue (FastAPI saare load karta hai via router imports, Celery nahi).

Fix: `src/celery/worker.py` mein early import:

```python
from src.app.core.tenants import models as _tenants_models  # noqa: F401
```

### Issue 6 — `ContactCreate validation error`

Meta Testing Tool synthetic `<test lead: dummy data for X>` placeholders return karta hai jo phone format validation fail karte hain.

Fix already applied: `src/app/core/integrations/meta/tasks.py` ke `_apply_mapping` function mein dummy pattern detection:

```python
if isinstance(value, str) and value.startswith("<test lead: dummy data"):
    continue
```

### Issue 7 — `Pages & Forms: No Pages found` in CRM

OAuth flow ne Pages access nahi diya. Fix:
1. CRM Settings → Meta card → **Disconnect**
2. **Connect** wapas → FB consent mein **"Opt in to all current and future Pages"** select karo
3. All permissions ON karo

### Issue 8 — Webhook verify fail (Meta dashboard mein red error)

Verify Token mismatch. Check karo:
1. `secrets.enc.env` mein `META_WEBHOOK_VERIFY_TOKEN` value (`run.cmd secrets-edit` se dekho)
2. Meta dashboard webhook field mein same value
3. Trailing spaces / hidden chars nahi hone chahiye

### Issue 9 — `pages_manage_ads` permission error (Meta v25+)

Meta API v25+ leadgen_forms endpoint pe `pages_manage_ads` mandatory hai. OAuth `_SCOPES` mein add:

```python
_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_metadata",
    "pages_manage_ads",   # <-- critical
    "leads_retrieval",
    "business_management",
]
```

CRM mein Disconnect + Reconnect karo new permission ke saath.

---

## Code-level Fixes Applied (Session Summary)

| # | File | Fix |
|---|------|-----|
| 1 | `API/requirements.txt` | Added `celery[redis]`, `flower`, `psycopg2-binary` |
| 2 | `API/docker-compose.yml` | Secrets reach celery/beat/flower via the `x-secret-vars` passthrough (SOPS `exec-env`) — no MASTER_KEY |
| 3 | `API/docker-compose.dev.yml` | `DB_NULL_POOL=1` env var + `.:/app` volume mount on celery/beat/flower |
| 4 | `API/src/core/db.py` | Conditional NullPool based on `DB_NULL_POOL` env var |
| 5 | `API/src/celery/worker.py` | `worker_process_init` + `task_prerun` signals for engine disposal |
| 6 | `API/src/celery/worker.py` | Early import of `src.app.core.tenants.models` for ORM metadata |
| 7 | `API/src/app/main.py` | Import `src.celery.worker.celery` to bind Celery app in API |
| 8 | `API/src/app/core/integrations/meta/oauth.py` | Added `pages_manage_ads` to `_SCOPES` |
| 9 | `API/src/app/core/integrations/meta/tasks.py` | `_apply_mapping` skips Meta's `<test lead: dummy data>` placeholders |

---

## Daily Restart Checklist (after laptop reboot)

```
1. ngrok start karo:
   ngrok http 8000
   → Naya URL note karo

2. config.env mein META_OAUTH_REDIRECT_URI update karo with new ngrok URL

3. Meta dashboard mein 2 URLs update karo:
   - Facebook Login → Settings → Valid OAuth Redirect URIs
   - Use cases → Capture & manage ad leads → Customize → Webhooks → Callback URL
     (+ Verify and Save)

4. Docker stack up karo (run.cmd secrets ko in-memory decrypt karta hai):
   cd C:\Users\USER\Desktop\Projects\crm\API
   run.cmd up

5. Wait 60 sec, phir verify:
   curl http://localhost:8000/api/v1/health
   curl https://<ngrok>.ngrok-free.app/api/v1/health

6. Frontend start karo:
   cd C:\Users\USER\Desktop\Projects\crm\APP
   npm start

7. Browser: http://localhost:4200 → login → ready
```

---

## Pipeline Verification Checklist

| Check | Status |
|-------|--------|
| ngrok tunnel reachable from internet | ✅ |
| Backend health endpoint OK (local + ngrok) | ✅ |
| Celery worker ready, NullPool active | ✅ |
| Webhook URL verified in Meta dashboard (green tick) | ✅ |
| `leadgen` field subscribed | ✅ |
| OAuth flow connects CRM to Meta with all 6 permissions | ✅ |
| Page subscribed (POST /pages/{id}/subscribe → 200) | ✅ |
| Lead Form published on Page | ✅ |
| Subscription record created with field_mapping | ✅ |
| Lead Access Manager configured (People + CRMs) | ✅ |
| Test webhook (Send to server) → DLQ entry created | ✅ |
| Real leadgen_id manual task fire → status='created' | ✅ |
| CRM `/user/leads` shows lead with Source: Meta Ads | ✅ |

---

## Production Launch — Future Work

### Pending items for production

1. **Meta App Review** — `leads_retrieval`, `pages_manage_metadata`, `pages_read_engagement`, `pages_show_list`, `pages_manage_ads` for advanced access. 1-3 weeks review.
2. **Business Verification** — Meta requires legal entity verification (3-7 days).
3. **Privacy Policy URL** — Real policy page (not Google's).
4. **Static HTTPS** — Replace ngrok with Cloudflare Tunnel ya cloud hosting (Render/Railway/AWS).
5. **App Live Mode** — After App Review approval, flip to Live Mode for public customers.
6. **Meta card UI gap** — Currently meta-card.component.html mein per-form Subscribe + Edit Mapping button missing hai (Google card mein hai). Add karna hai for proper Settings UX.
7. **DLQ FK constraint** — `integration_dlq.org_id` fallback to `00000000-...` synthetic UUID violates FK. Either make column nullable OR insert synthetic system org row OR skip DLQ when org unknown.

### Operational

- ngrok URL rotation: free tier mein har restart pe change → automate `config.env` update + Meta dashboard sync via script
- Monitor DLQ regularly — failed webhooks/leads operator intervention chahiye
- Set up alerts for `processed=0` over time window (might indicate Meta delivery issue)

---

## Reference Links

- Meta App Dashboard: [developers.facebook.com/apps](https://developers.facebook.com/apps)
- Lead Ads Testing Tool: [developers.facebook.com/tools/lead-ads-testing](https://developers.facebook.com/tools/lead-ads-testing)
- Graph API Explorer: [developers.facebook.com/tools/explorer](https://developers.facebook.com/tools/explorer)
- Business Manager: [business.facebook.com](https://business.facebook.com)
- Ads Manager: [adsmanager.facebook.com](https://adsmanager.facebook.com)
- ngrok Dashboard: [dashboard.ngrok.com](https://dashboard.ngrok.com)
- SOPS secret management: [`API/SOPS_INTEGRATION_GUIDE.md`](API/SOPS_INTEGRATION_GUIDE.md)

---

## Quick Reference — Useful Commands

### Backend logs (live)

```powershell
docker logs crm-celery-1 --follow
```

### Filter Meta-related logs

```powershell
docker logs crm-celery-1 --since 5m 2>&1 | findstr /i "process_meta"
```

### Health checks

```powershell
curl http://localhost:8000/api/v1/health
curl https://<ngrok>.ngrok-free.app/api/v1/health
```

### Pool type check

```powershell
docker exec crm-celery-1 python -c "from src.core.db import engine; print('Pool:', type(engine.sync_engine.pool).__name__)"
```

### List leads for a form via Meta API

```powershell
docker exec crm-celery-1 python -c "import asyncio, httpx, asyncpg; from src.app.core.integrations.crypto import decrypt; from config import DB_PASSWORD, DB_HOST, DB_PORT, DB_USER, DB_NAME; loop = asyncio.new_event_loop(); c = loop.run_until_complete(asyncpg.connect(host=DB_HOST, port=int(DB_PORT), user=DB_USER, password=DB_PASSWORD, database=DB_NAME)); row = loop.run_until_complete(c.fetchrow(\"SELECT page_token_enc FROM meta_page_tokens WHERE page_id='<PAGE_ID>'\")); token = decrypt(row['page_token_enc']); loop.run_until_complete(c.close()); h = httpx.Client(); r = h.get('https://graph.facebook.com/v19.0/<FORM_ID>/leads', params={'access_token': token, 'limit': 50}); print(r.json())"
```

### Manual task fire with real IDs

```powershell
docker exec crm-celery-1 python -c "from src.celery.worker import celery; from src.app.core.integrations.meta.tasks import process_meta_lead; result = process_meta_lead.delay({'leadgen_id': '<REAL_ID>', 'form_id': '<FORM_ID>', 'page_id': '<PAGE_ID>', 'ad_id': None, 'campaign_id': None, 'created_time': 1780472068}); print('Task queued:', result.id)"
```

### Service status

```powershell
docker compose --env-file config.env -f docker-compose.yml -f docker-compose.dev.yml --profile celery ps
```

### Down + Up (after config.env / secrets.enc.env / docker-compose changes)

```powershell
run.cmd restart
```

(`run.cmd restart` = down + up, secrets in-memory decrypt karke. Raw `docker compose up` ke saath secrets empty aayenge.)

---

**Document last updated**: 2026-06-22 (secrets migrated to SOPS + age; stack runs via `run.cmd` / `run.sh`)  
**Pipeline status**: Production-ready code-level. Real lead arrival depends on Meta-side delivery (Testing Tool) or paid ad campaign.

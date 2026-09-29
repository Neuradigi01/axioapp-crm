# Cloudflare R2 setup runbook (Step 0)

Do this **three times**, once per environment. Each environment gets its own Cloudflare account, bucket and API token.

| Environment | Sign up with | Bucket name | Secrets file |
|---|---|---|---|
| `local` | dev@karmcrm.com | `crm-local` | `secrets.local.enc.env` |
| `prod` | aixoindia@gmail.com | `crm-prod` | `secrets.prod.enc.env` |
| `prod-neuradigi` | admin@karmcrm.com | `crm-neuradigi` | `secrets.prod-neuradigi.enc.env` |

Cloudflare occasionally renames buttons. If a label below doesn't match exactly, look for the closest equivalent.

## 1. Create the Cloudflare account

1. Open https://dash.cloudflare.com/sign-up
2. Sign up with the email from the table and verify it from the inbox.
3. Skip "add a website / domain". R2 doesn't need one.

## 2. Enable R2

1. Open https://dash.cloudflare.com/?to=/:account/r2/overview1c3192a25b271b173e78ca2f7311ad3a2d8229e9b3ae21b64b0fa3babec850b2
2. Cloudflare asks you to **add a payment method** (card or PayPal) before R2 turns on. This is required even on the free tier: the first 10 GB of storage each month is free, and you are only charged beyond that.
3. Confirm and enable the R2 plan.

## 3. Create the bucket

1. On the R2 overview page, click **Create bucket**.
2. **Name:** the bucket name from the table (e.g. `crm-prod`).
3. **Location:** Automatic, or choose the **Asia-Pacific (APAC)** location hint, since the servers and users are in India.
4. **Default storage class:** Standard.
5. Click **Create bucket**.
6. **Do NOT enable public access.** Leave the "Public Development URL" (`r2.dev`) **disabled** and don't connect a custom domain. The CRM reads files privately.

## 4. Create the API token (keys)

1. Open https://dash.cloudflare.com/?to=/:account/r2/api-tokens
   (or go to R2 overview → **Manage API tokens**)
2. Click **Create API token**. Choose the **Account API token** if it asks which kind.
3. **Name:** `crm-api-<env>` (e.g. `crm-api-prod`).
4. **Permissions:** **Object Read & Write**.
5. **Specify bucket(s):** **Apply to specific buckets only**, then choose the bucket you just created.
6. **TTL:** Forever.
7. Click **Create API Token**.
8. The next screen shows the keys **only once**. Copy these two values somewhere safe right away:
   - **Access Key ID**
   - **Secret Access Key**
9. Copy the **Account ID** too. It's on the R2 overview page (right side, "Account details"). It's also the first part of the S3 endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.

## 5. Put the keys into the CRM secrets

Don't paste the keys into chat, Slack, email or any plain file.

1. Set `API/.environment` to the environment you're filling in (`local`, `prod` or `prod-neuradigi`).
2. From `API/`, run `run secrets-edit` (`run.cmd secrets-edit` on Windows).
3. Add these four lines at the bottom and save:

   ```
   R2_ACCOUNT_ID=<Account ID>
   R2_ACCESS_KEY_ID=<Access Key ID>
   R2_SECRET_ACCESS_KEY=<Secret Access Key>
   R2_BUCKET=<bucket name, e.g. crm-prod>
   ```

4. Repeat for the other two environments, then set `API/.environment` back to `local`.

Adding the keys alone changes nothing. The CRM keeps using local disk until Step 7/8 flips `STORAGE_BACKEND=r2` for that environment.

## Checklist to report back

- [ ] local: account, `crm-local` bucket, token, 4 secrets added
- [ ] prod: account, `crm-prod` bucket, token, 4 secrets added
- [ ] prod-neuradigi: account, `crm-neuradigi` bucket, token, 4 secrets added
- [ ] Public access (`r2.dev`) left **disabled** on all three buckets

## If a key ever leaks

Go to R2 → Manage API tokens, **roll** or delete the token, create a new one, and update it with `run secrets-edit`. Only that one environment's bucket is affected.

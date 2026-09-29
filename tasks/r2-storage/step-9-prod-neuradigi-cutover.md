# Step 9: prod-neuradigi cutover (runbook)

**Status:** Pending. This must run on the neuradigi server by someone with shell access.
**Depends on:** Step 8, and the track's code deployed to the neuradigi server.

Bucket `crm-prodneuradigi` (Cloudflare account admin@karmcrm.com). The `R2_*` keys are already in `secrets.prod-neuradigi.enc.env`.

`prod` (aixo) repeats this runbook later with its own bucket, once its Cloudflare account exists.

## Before you start

- Pick a quiet time. There are two short container restarts.
- Deploy the code from this track while `STORAGE_BACKEND` is still `local`. Do **not** commit `STORAGE_BACKEND=r2` to `config.prod-neuradigi.env` before step 3 below.

## Steps (on the server, in `API/`, with `.environment` = `prod-neuradigi`)

1. **Rebuild with the new code** (boto3 and the Celery driver fix): `./run.sh up`
   - Check that the app works, and that `docker logs <celery container>` shows "ready" and no `psycopg` error.
2. **Pre-flip copy:**
   - Run `./run.sh storage-migrate --dry-run` and read the counts. `failed` must be 0.
   - Run `./run.sh storage-migrate`. `failed` must be 0.
3. **Flip:** add `STORAGE_BACKEND=r2` to `config.prod-neuradigi.env`. Commit it so the next deploy keeps it. Then:
   - Run `./run.sh up` (recreates **every** container: api, celery, beat).
   - Confirm each one with `docker exec <container> env | grep STORAGE_BACKEND`.
4. **Catch-up copy** (anything written to disk between steps 2 and 3): `./run.sh storage-migrate --only-missing`
5. **Smoke test in the browser:**
   - The public store page and property listing images load.
   - A chat-widget avatar loads.
   - A catalog image upload saves and displays.
   - A lead import runs, and its errors CSV downloads.
   - A call recording plays.
   - An inbound email attachment downloads.
   - Opening any `…/files/<org>/imports/…/source.csv` URL returns 404.
6. **Keep `./storage` on the server for 30 days** as a second copy.
   - Removal date: cutover date + 30 days.
   - Owner: whoever ran the cutover. Record both here when done.

## Rollback

1. Run `./run.sh storage-migrate --reverse`.
2. Remove `STORAGE_BACKEND=r2` from `config.prod-neuradigi.env`, then run `./run.sh up`.
3. Run `./run.sh storage-migrate --reverse --only-missing`.

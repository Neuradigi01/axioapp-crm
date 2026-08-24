# CI/CD Bootstrap — a prompt for another project

Hand the block below to an AI agent working in a different repository. It carries
the design decisions and the failures from building this one, so that project does
not rediscover them one hour at a time.

Everything below the line is the prompt. Fill in the **Context** section first —
the rest is deliberately project-agnostic.

---

## Your task

Build continuous **deployment** for this project. CI (lint/test on PR) already
exists; what is missing is everything that gets a green commit onto a server.

Produce five things:

1. `deploy/deploy.sh` — idempotent deploy, run on the server
2. `deploy/setup.sh` — one-time server provisioning, resumable
3. `.github/workflows/deploy.yml` — pushes to the deploy branches trigger it
4. `deploy/nginx/<hostname>.conf` — one per environment
5. `docs/DEPLOYMENT.md` — the runbook, including a "things that cost us an hour
   each" section you append to as you hit them

**Work in stages and stop between them.** Provisioning a server is not work you
batch: each failure teaches you something about that machine. Get `deploy.sh`
working by hand on the non-production server first, then automate it, then do
production. Never automate a deploy you have not watched succeed manually — the
first failure is the most informative one, and you do not want to read it through
an Actions log with no terminal.

### Context to fill in before you start

Ask the user for these; do not guess:

- Environments and their branches (e.g. `staging` ← `dev`, `production` ← `main`)
- Each server's host, SSH port, deploying user, deploy path
- OS and firewall — this guide assumes AlmaLinux/RHEL + firewalld; Debian/ufw
  needs translating
- Whether each box is **dedicated or shared**. This changes almost every
  destructive decision below
- Where the database lives: in the app's compose stack, or on the host?
- What the app is made of (API, SPA, SSR site, worker, embeddable script) and
  which parts need a build vs a process restart

---

## Non-negotiable design decisions

Each of these was arrived at by getting it wrong first.

### One environment marker on the server, not a flag in the workflow

The server holds a file naming what it is (`prod` / `staging` / `local`). Every
script reads it to select config, secrets, the compose overlay, and the frontend
build configuration.

**The workflow passes no `--env` argument.** It therefore cannot aim a staging
deploy at production by getting a parameter wrong; the worst a bad secret can do
is fail to connect.

### Per-environment secrets files, encrypted, one key per server

Use SOPS + age or equivalent. One encrypted file **per environment**, no shared
base file — essentially every value should differ between environments, and a
shared signing key means a token minted on staging authenticates against
production.

**Generate each server's key ON that server** so the private half never travels. A
personal key copied to a server means the server's access is really that person's
access, and revoking them silently breaks deployment.

The isolation is then mathematical rather than procedural: the staging server's
key is not a recipient of the production file, so it *cannot* decrypt it.

### The deploy SSH key is restricted to one command

In the deploying user's `authorized_keys`:

```
restrict,pty,command="/path/to/deploy/deploy.sh",expiry-time="YYYYMMDD" ssh-ed25519 AAAA... github-actions-<env>
```

`restrict` denies forwarding, X11 and user-rc. `pty` is added back because the
workflow uses `ssh -tt`. `command=` means the server runs that script and nothing
else, whatever the client asks for. A holder of this key can redeploy your code
and cannot open a shell, read a file, or reach any other service on the box.
**That is why an unencrypted private key in GitHub Secrets is acceptable here.**

Restrictions are per-key, so the user keeps their normal login key alongside it. A
separate `deploy` account is unnecessary — the forced command bounds the blast
radius, not the username.

**Test it with `command="/usr/bin/id"` first.** Connect, ask for something else,
and confirm you get `uid=…` back rather than what you asked for. Only then point
it at the real script. Skip this and, if the command is wrong, CI connects
happily, runs the wrong thing, exits 0, and reports a **green deploy that deployed
nothing**.

### GitHub environment secrets, not repository secrets

Create one GitHub Environment per deploy target; the workflow selects it from the
branch name. Put host, port, user, key, known_hosts and deploy path in the
**environment**, so a staging run cannot read production's credentials at all.

Also set **Deployment branches** to the single branch allowed to deploy there, and
**Required reviewers** on production if the plan allows it. That last one turns
continuous deployment into deliberate deployment, and it is the only thing
standing between a merge and a live change.

### Seeds run on every deploy; the seed layer decides which

Reference data that ships WITH a commit — a new route, a permission, a catalog
entry — must reach the database that commit needs it in. A step someone runs
manually afterwards is a step that gets missed the moment CI deploys without a
human present, and the symptom is a missing menu row with nothing in the log to
explain it.

So `deploy.sh` runs the seeds unconditionally **and names none of them.** Classify
every seed in the seed layer, with no default:

- **every-deploy** — idempotent upserts. Safe unattended, on any environment.
- **fresh-only** — anything that RECONCILES, i.e. deletes rows its source file no
  longer lists. Correct when an operator applies a catalog change by name; wrong
  as a side effect of deploying, because a hand-added row vanishes without anyone
  being asked. Gate these on whether the database holds real user data — **not on
  the environment name.** Production on day zero is genuinely fresh and should get
  everything; a local database with real data should not lose rows either. What
  deserves protection is data; the environment is only a proxy for it.
- **manual-only** — demo fixtures, expensive rebuilds. Never automatic.

Write a test asserting every seed is in exactly one class, **then verify that test
fails when you deliberately misclassify one.** A test that passes today but would
not catch the mistake is decoration.

---

## `deploy.sh` requirements

- **Anchor itself**: `REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$REPO_ROOT"`.
  A forced-command SSH session starts in the home directory, not the repo.
- **Two-phase preflight.** Check *tooling* before updating source; check
  *configuration* after. Validating config before the pull means a fix you just
  pushed can never clear the error — you are checking the old file.
- **Back up the database before migrating**, keep the last N, and print the path in
  every failure message alongside the rollback command.
- Update source with `git fetch` + `git reset --hard @{u}`, not `git pull`.
- Order: migrations → seeds → builds → process restarts → health check with a
  timeout.
- **Frontend builds must name their configuration explicitly.** Never rely on the
  default: it will quietly produce a staging bundle pointed at production, and
  every log line will say the build succeeded.
- After the health check, verify the **running code matches the migration** it
  reports. A container that restarted from a stale image looks exactly like
  success.
- Support deploying **parts** (api / frontend / worker) so a frontend-only change
  need not migrate.
- Persist the process manager's list after restarts (`pm2 save --force`), or the
  server works perfectly until it reboots.

## `setup.sh` requirements

- **Resumable.** It will fail partway; re-running must be safe.
- Copy it to the server *before* cloning — it generates the key that lets the
  server clone, so it cannot come from the repo it is about to clone.
- **Pause** where the user must act off-machine (registering a deploy key, sending
  an age public key to whoever manages secrets) and require a typed confirmation,
  not any keypress.
- End with a **decryption gate**: prove this machine can decrypt its own secrets
  before declaring success.
- Leave package installation, nginx and TLS **manual**. They depend on what is
  already on the machine and a script cannot tell — especially on a shared host.

---

## The failures to design against

Every one of these cost an hour or more. Most fail *silently*, or with an error
naming the wrong thing.

### Shell

- `ssh -T git@github.com` **exits 1 on success.** Under `set -o pipefail` the
  obvious connectivity check can never pass. Capture the output first, then grep
  it.
- `<cmd> | head -1` under `pipefail` fails on SIGPIPE. Capture into a variable
  with `|| true`.
- **`| tail` swallows the exit code** of the command before it. You will report a
  failing run as passing. Grep for the result explicitly, or check the real status.
- **A script that updates itself mid-run is executing a file that changes
  underneath it.** Bash reads scripts incrementally by byte offset, so a
  `git reset --hard` during a deploy can drop it mid-line into new content. In
  practice it usually survives, and it *always* means a change to the deploy script
  takes effect one deploy late. Copy to a temp file and re-exec, or accept it
  knowingly.
- **Never use blind `sed -i` on source.** It replaces every match silently and
  leaves no diff; on a repo full of repeated patterns that is a wrong edit you find
  late, or never.

### Server

- **`firewall-cmd --reload` flushes iptables and takes Docker's chains with it.**
  Docker never rebuilds them, so the next container needing a published port dies
  with `Unable to enable DNAT rule: iptables: No chain/target/match by that name`,
  naming neither firewalld nor the reload that caused it. Follow every reload with
  `systemctl restart docker` — and on a shared box, check what else went down.
- **Directories created by a container are owned by root.** Create data
  directories during provisioning with the **numeric** uid/gid the container runs
  as, not `$USER`: the deploying user's uid differs between machines, and the
  failure surfaces as a permission error deep in application startup.
- **Worker count × memory limit must fit the container's cgroup**, or you get an
  OOM restart loop that reads as an application crash.
- Every secret the app needs must actually be **passed into** the container.
  Decrypting successfully and then failing to forward a variable yields an empty
  value and a failure far from its cause.

### Database

- **Extensions are not installed by migrations.** If the schema needs one
  (`vector`, `postgis`, `uuid-ossp`), a host-installed database will not have it,
  while local and CI often do because they use an image that ships it. Document it
  as a prerequisite, and check for it in preflight if you can.
- **An app in a container connects from the container's address**, not the host's.
  A host-based database's `pg_hba.conf` needs the container subnet — allowing the
  server's own public IP does nothing. Allow the private range, then close the
  database port to the internet entirely.

### SSH and Actions

- **`ssh-keyscan` needs `-p <port>` on a non-standard port.** Without it you get an
  unbracketed line that can never match, and the failure reads
  `No ED25519 host key is known for [***]:***` with the host masked. The correct
  form is `[host]:port ssh-ed25519 …`.
- **Store `known_hosts` as a secret rather than scanning at deploy time.** Keyscan
  trusts whatever answers first, which is precisely the moment an impostor would
  want to be believed. Verify the fingerprint on the server console before trusting
  it.

### Application

- **SSR frameworks often refuse unknown hostnames**, or silently de-optimise behind
  a proxy unless told which forwarded headers to trust. Add every public hostname
  to the allowlist and configure proxy-header trust explicitly.
- **A cache with no TTL is invalidated by nothing except code that clears it.** If
  seeding writes data the app caches at startup, refresh that cache in the seed
  path — and make sure the cache client is actually connected first. A standalone
  script has not run the app's startup, and a cache-write helper that returns
  silently when the client is missing, paired with a log line printed
  unconditionally, will report a refresh that never happened.
- **A placeholder token that blocks deploys will match your own comment about it.**
  If preflight greps for `FILL_IN`, a comment explaining the placeholder blocks
  every deploy, with an error pointing at a comment.

---

## `docs/DEPLOYMENT.md` — what it must contain

Write for someone provisioning a **new** server a year from now who was present
for none of this.

1. The shape — what runs where, which branch deploys to which environment
2. A table of servers: host, SSH port, branch, environment marker, dedicated or shared
3. Numbered provisioning steps, saying which are automated and which stay manual **and why**
4. Database prerequisites, separately — they are provisioned outside the app and nothing checks them until a migration fails
5. The CI/CD step **last**, explicitly gated on a successful manual deploy
6. **Things that cost us an hour each** — the running list. This is the highest-value section in the file; append to it every time something surprises you
7. Ports and what listens on them, plus how to check what is free before picking one
8. Rollback: the exact command, and where the backups are
9. What is deliberately **not** automated, and why

Write for a reader who is mid-incident: commands they can paste, with the reason
underneath so they can tell when it no longer applies.

---

## How you will know you are done

- `deploy.sh` has succeeded **by hand** on every server
- A push to each deploy branch produces a green run that visibly did the work —
  check a timestamp or a build artifact on the server, not merely the exit code
- The restricted SSH key has been proven to refuse an arbitrary command
- Each server decrypts only its own secrets
- A new person can follow `DEPLOYMENT.md` to provision a third server without
  asking you anything

**Report honestly.** Paste the output of what you ran, and name what you did not
run. A deploy reporting success in 90 seconds when it should take ten minutes has
not done the work — check the server before believing the log.

# Supabase SQL and account mode

The dedicated **Cadence** project uses PostgreSQL 17 in US East. Project reference: `ycxvyspncoleszywqorp`. The initial project quote was $0/month; normal service limits still apply.

## Runtime configuration

Install requirements, copy `.env.example` to `.env`, then fill `SUPABASE_URL` and the modern `sb_publishable_...` key from the project's Connect/API settings. No database password or service-role key is needed. `.env` is ignored by Git.

With both values configured, `cadence.api:create_app` serves Supabase mode. Without either value, it serves the original SQLite demo. An incomplete configuration fails explicitly instead of silently falling back to an unauthenticated application.

```bash
uvicorn cadence.api:app --host 127.0.0.1 --port 4180
```

- `/`: email/password sign-up and sign-in, email-confirmation messaging, sign-out, refresh rotation, private history and analytics.
- `/demo/`: no-account showcase backed by synthetic Supabase data. Select among 40 fictional listeners, play audio, explore recommendations, run SQL reports, and inspect offline metrics. Guest playback is intentionally not stored.
- `/api/sql/queries` and `/api/sql/run`: predefined, bounded SQL reports. Private reports derive identity in PostgreSQL from `auth.uid()`; they do not trust user IDs from a browser.
- `/api/export`: authenticated ZIP download of the caller's de-identified analytics CSVs, matching the Power BI semantic-model columns. The model evaluation CSV is the fixed synthetic benchmark, not an account metric.

## Authentication and data isolation

Passwords are forwarded to Supabase Auth and never stored by Cadence. Access and refresh tokens use HttpOnly, SameSite=Lax cookies scoped to `/api`. HTTPS requests use Secure cookies; set `COOKIE_SECURE=1` behind a trusted HTTPS reverse proxy. Cross-origin writes are rejected. Supabase's Auth server verifies the user token before private requests. Browser JavaScript does not hold tokens in localStorage.

Every application table has row-level security enabled. Catalog rows have public read policies. Real user tables have no direct browser grants; narrow, fixed-search-path SQL functions check the authenticated identity before accessing private rows. The model sees public synthetic seed interactions plus the caller's own real history, never another real listener's history.

Supabase's advisor flags privileged functions for review. These owner-scoped commands intentionally use SECURITY DEFINER to avoid direct client table-write grants, with explicit execute grants, fixed search paths, and identity checks. Public demo functions return `is_demo=true`/`source='seed'` rows only. Relevant advisory documentation: [function execution review](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable).

`supabase/tests/account_isolation.sql` is a live PostgreSQL integration test. It creates two temporary auth identities inside a transaction, checks cross-account write rejection and history/training/analytics isolation, and rolls everything back. No test users remain. Unit tests mock Supabase Auth for token/cookie flows; they do not send confirmation emails.

## SQL source and seed data

Apply migrations in order from `supabase/migrations/`. The dedicated schema is `cadence`; public API functions are prefixed `cadence_`. Seed batches in `supabase/seed/` contain only the deterministic synthetic dataset and should be applied in filename order to a fresh schema. They must not be applied over unrelated user data. Generate them with `python -m scripts.export_supabase_seed`.

The live project has the migrations and seed applied. New projects can use the Supabase CLI or SQL editor. Never commit database credentials or a service-role key.

## Email confirmation and public signup

Keep email confirmation enabled. Set the project Site URL to the hosted application URL and add exact local development URLs to the redirect allowlist. Email confirmation does not automatically create a browser session in Cadence: return to the app and sign in after confirming.

Supabase's default SMTP sends only to organization/team addresses. Configure a custom SMTP provider before inviting arbitrary recruiters/users to create accounts; the no-account demo works without SMTP. [Official SMTP documentation](https://supabase.com/docs/guides/auth/auth-smtp).

## Hosting

`app.py` is Vercel's supported FastAPI entrypoint. Set `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and `COOKIE_SECURE=1` in the Vercel project. Python 3.13 is selected in `.python-version`. The 24 original demo WAV files are bundled under `cadence/static/audio` so the serverless runtime never needs to write audio to its read-only filesystem. Supabase owns persistence; runtime state is not stored in a local database in cloud mode.

## Live playback and request quotas

The hosted client sends cumulative heard time every five seconds while playing,
and flushes on pause, track change and page exit. `/api/playback/progress` uses
one stable event key per listening occurrence. PostgreSQL atomically keeps the
maximum duration, so retries and out-of-order requests cannot add extra plays
or reduce listening time. Analytics refresh every five seconds while the tab
and Listening Lab are visible. This is near-real-time polling, not WebSockets;
completion/skip percentages include progress heard so far and can change during
playback. Abrupt browser termination can lose the last unsent interval.

Guest playback appears as a tab-local overlay on the 4,480 synthetic seed plays.
It resets on reload, is never written to private tables, and does not change
SQL Studio's sample reports. Signed-in progress is stored in Supabase.

Shared PostgreSQL fixed windows protect the hosted API, including `/demo`:

| Scope | Requests per IP per minute |
| --- | ---: |
| Auth | 10 |
| Recommendations | 20 |
| SQL execution | 30 |
| Playback | 120 |
| Audio | 180 |
| Other API requests | 120 |

Excess requests return 429 with `Retry-After`; successful requests include
`X-RateLimit-Limit` and `X-RateLimit-Remaining`. A limiter outage fails closed
with 503. Windows align with UTC minutes and can permit a burst across a minute
boundary. Vercel's overwritten `x-vercel-forwarded-for` identifies clients;
local servers use the socket peer and ignore forwarded headers. Other proxy
hosting needs an explicit trusted-proxy design. IP hashes are retained for at
most a day plus bounded lazy cleanup; raw addresses are not stored. Hashes are
pseudonymous, not anonymous identifiers.

Account database triggers independently enforce 120 playback writes, 30 sessions,
20 recommendation requests and 60 likes per minute, including direct authenticated
RPC requests. Quotas are shared across instances and use atomic UPSERTs.
This is application throttling, not edge-level DDoS protection. Direct anonymous
Supabase sample-read RPCs are not covered by the Vercel IP middleware. The public
quota RPC accepts only fixed scopes and hashed subjects; it cannot access private
account data. For a high-traffic launch, also configure Vercel firewall controls.

Security advisor findings are intentional: the quota table has deny-by-default
RLS with no browser grants/policies; its private helper is not executable by
browser roles. The scoped public quota and owner-checked progress RPCs use fixed
search paths and explicit grants. `supabase/tests/live_playback.sql` verifies
monotonic progress, deduplication, ownership, quota rejection/reset and grants
inside a rolled-back transaction.

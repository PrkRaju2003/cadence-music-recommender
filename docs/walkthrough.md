# A 60-second recruiter walkthrough

Open **https://cadence-prk.vercel.app/demo/**. No account is needed.

1. **Compare taste (15 seconds):** look at Alex Morgan's mix, then switch to Listener 02. Recommendations change because these synthetic listeners have different histories.
2. **Play a track (10 seconds):** open the catalog, search for a song, and press play. The player streams an original 12-second WAV clip with pause/seek/next controls. Demo playback is not saved to real accounts.
3. **Inspect the reasoning (10 seconds):** return to Discover and expand “How it works.” Explain the 50% collaborative, 35% sequence, 15% popularity blend. These are ranking signals, not probabilities.
4. **Run SQL (10 seconds):** open SQL studio, choose Catalog by genre or My top tracks, and run the report. Results come from Supabase PostgreSQL, not a hardcoded table in the frontend.
5. **Check evidence (15 seconds):** open Listening lab for engagement and chronological holdout comparisons. Explain that the benchmark uses synthetic data and is not a claim about real-user uplift.

## What to put on the portfolio

- Title: **Cadence — Music Streaming & Hybrid Recommendations**
- Links: **Try live demo** and **View source**
- Scope: 40 synthetic listeners, 24 original audio clips, 4,480 seed plays
- Stack: Python, FastAPI, SQL/PostgreSQL, Supabase Auth, Vercel, Power BI report project
- Evidence: architecture/ER diagram, baseline comparison, CI status, screenshots, and the hosted HTTP check

The portfolio already links this project. Sign-in is optional for reviewers; real users can create accounts to save private histories. Public email signup requires custom SMTP because Supabase's built-in sender is limited to organization/team addresses.

## How to check it later

```bash
python scripts/smoke_showcase.py --base-url https://cadence-prk.vercel.app
```

This checks the live database health, 40 demo listeners, 24 tracks, different recommendations for two listeners, actual SQL reports, 206 audio range responses, and 401 protection on private routes. It creates no accounts and sends no emails. Unit tests and Docker CI provide separate engineering evidence.

Use screenshots and this walkthrough as fallback evidence if a free hosting/database project is paused. Do not represent seeded listeners as real customers. Power BI report JSON is schema-validated; Power BI Desktop rendering still needs a Windows check.

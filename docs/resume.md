# Resume wording tied to the implementation

**Cadence — Music Streaming & Hybrid Recommendation System**  
Python · FastAPI · SQL · Collaborative Filtering · Markov Models · Power BI

Implemented and locally verified:

- Designed a normalized relational schema for users, artists, albums, tracks, listening sessions, and playback history; enforced foreign keys, uniqueness and playback constraints, and verified indexed query plans.
- Built a hybrid next-track and album recommender combining item-item collaborative filtering, session-level Markov transitions, and popularity; evaluated four ranking strategies using chronological holdout, Hit Rate@5, NDCG@5, MRR@5, and catalog coverage.
- Served recommendation, playback, and analytics endpoints through FastAPI; authored a Power BI report project with an import semantic model, DAX measures, and de-identified CSV exports for engagement and model monitoring.

After opening, refreshing, and visually validating the report in Power BI Desktop, the last bullet can say “created a Power BI dashboard.” After deploying a persistent backend to a real hosting environment, “served” can become “deployed.” Do not claim a public deployment before it exists.

Optional evidence-based detail: the reproducible demo includes 40 synthetic listeners, 24 generated audio tracks, and 4,480 seeded playback events. These are test-data counts, not real users or business traction.

Avoid presenting the high synthetic benchmark scores as real-user recommendation accuracy. Explain the fixed component weights, small catalog, and first-order sequence model in interviews. No Transformer, large-scale distributed training, commercial music catalog, or production authentication is implemented.

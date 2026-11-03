# Unstable Universe Analyzer

Cloud research pipeline: YouTube channels → relevant-video discovery → frame extraction (ffmpeg) → two-pass vision analysis
(Claude) → cross-channel entity merge → SQLite DB → versioned, checksummed HTTPS export for ChatGPT Work.

## Status (honest)
| Area | State |
|---|---|
| Multi-channel input, discovery (yt-dlp), relevance reason, 2026-01-01 cutoff, historical separation | Implemented. **Not tested against live YouTube** (sandbox proxy returns 403 for youtube.com) |
| Durable queue (leases, crash recovery, pause/resume/retry), concurrency limit | Implemented + unit-tested |
| Frame extraction with true timestamps (scene change + min interval) | Implemented + tested on a generated video |
| Vision analysis, 2 passes, "analyzed" only when all frames done | Implemented; plumbing tested with a **test-only fake model**. **No real analysis has run**: no `ANTHROPIC_API_KEY` and no YouTube access in the build sandbox |
| Entity merge / dedupe / newest-wins / conflicts / unmerged duplicate candidates | Implemented + tested |
| Export (`manifest.json`, README, registries, per-civ, per-building, evidence frames, schemas, ZIP, SHA-256) | Implemented; served over HTTP and checksum-verified (0 mismatches) |
| Mobile UI (channels, videos, jobs, world explorer, missing info, Share button, history, MP4 upload) | Implemented; not yet verified on a physical iPhone |
| Schematics / block-coordinate plans | **Not implemented.** Footage gives estimates only; exports state `schematic_available:false` |
| Public deployment | **Not done** (see blockers) |
| ChatGPT Work handoff test | **Not done** — must be run by you (steps below) |
| The five sample buildings | **Not created** — none can be produced without real video analysis; none were fabricated |

## Blockers (exact)
1. **No hosting reachable from the build sandbox** (fly.io etc. blocked). Deploy yourself in ~5 minutes from a phone: Render → New → Blueprint → this repo (`render.yaml`). Cost ≈ $7/mo + disk.
2. **`ANTHROPIC_API_KEY`** needed for the vision stage (set as Render env var). Without it, jobs fail with a clear error.
3. **`ADMIN_TOKEN`**: any long random string; the UI prompts for it once.
4. **YouTube from datacenter IPs** is often bot-challenged by yt-dlp. If downloads fail, use the **MP4 upload** (Videos tab) for footage you are authorized to use, or supply cookies/proxy. Respect YouTube ToS and creators' rights; uploads/downloads are for private research.
5. Claude Code can't run ChatGPT Work, so the independent read-test can't be performed here.

## Run
`docker build -t ua . && docker run -p 8080:8080 -v ua:/data -e ADMIN_TOKEN=... -e ANTHROPIC_API_KEY=... -e RUN_WORKER_IN_API=1 ua`
Or API and worker as separate processes sharing `/data`: `uvicorn app.main:app` and `python -m app.worker`.
Tests: `pip install -r requirements.txt && pytest`.

## Handoff verification (do this after deploying)
1. Analyze at least one video (Videos tab, or upload an MP4); open **World** and confirm records with timestamps/screenshots.
2. **Share** tab → **SHARE WITH CHATGPT WORK** → copy the link (`https://<host>/x/<token>/manifest.json`).
3. In ChatGPT Work: *"Open this URL, read manifest.json, list every record id and name from registries/buildings.json, fetch two building files and one evidence image, and verify their SHA-256 against the manifest."*
4. Only if it lists the records correctly is the handoff proven. If its browser can't fetch the URL, try `/x/<token>/complete.zip`, or file an issue with its exact error.
Snapshot URLs are public capability URLs (unguessable 128-bit token, read-only, immutable, no credentials inside). Anyone with the link can read them.

## Design decisions
- SQLite on a persistent disk (WAL) – simplest durable store for one deployment; swap to Postgres + object storage for multi-node.
- Capability URLs for exports so ChatGPT Work needs no login. The admin API requires a bearer token.
- Hard rules in code: nothing is "analyzed" unless every frame had pass 1 and every flagged frame had pass 2; unknown stays `null`; names only from on-screen text; ambiguous scenes create open questions; near-duplicate names (0.65–0.88 similarity) are *listed*, not auto-merged; newest 2026+ footage defines current state, older is `history`.
- Weapons/machines are exported as specs only (never prebuilt).

## Capacity estimates (assumptions, not measurements)
- 300 h video at 720p ≈ 300 × ~0.7 GB ≈ **210 GB** transient (delete source after frames; keep frames ≈ 450 frames/h × 80 KB ≈ **11 GB** total).
- Frames: ~450/h (8 s floor, scene cuts add) → **~135k frames**; at 4 frames/request ≈ 34k pass-1 calls plus ~15–25 % pass-2. Estimated vision spend: **several hundred USD** (varies strongly with model pricing; check the Anthropic pricing page before bulk runs).
- Wall time: download+ffmpeg ≈ 5–10 min/h per worker; vision ≈ 15–30 min/h at 2 concurrent requests → **~1–3 days** for 300 h with 2–4 workers.
- Tuning knobs: `FRAME_MIN_INTERVAL_S`, `SCENE_THRESHOLD`, `FRAMES_PER_REQUEST`, `WORKER_CONCURRENCY`.
- Reality check: "every building" is not achievable from footage alone (unseen areas, no coordinates). Exports state `complete_world_claimed:false`.

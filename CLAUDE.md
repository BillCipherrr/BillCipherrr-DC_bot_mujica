# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Discord music bot ("Mujica") built with discord.py. Plays audio from 1,800+ sites via yt-dlp, supports queueing, multiple loop modes (including a history/YouTube-API-driven recommendation mode), per-guild volume/settings, play-history tracking in SQLite, and a MiniMax-powered `/tts` command. All in-code comments and user-facing strings are Traditional Chinese (zh-TW); keep new code consistent with that unless told otherwise.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot (also auto-initializes the SQLite DB on first run)
python bot.py
```

There is no lint/build tooling or CI configured in this repo, but there is a two-layer playback verification suite (see `docs/superpowers/specs/2026-08-20-playback-verification-tooling-design.md`):

```bash
# Layer A: fast, offline logic tests (mocks discord.py/yt-dlp, no network, no token). Run this after every code change.
pip install -r requirements-dev.txt
env -u PYTHONPATH pytest tests/

# Layer B: live smoke test against a real Discord test server/voice channel and real yt-dlp/YouTube.
# Run this after upgrading yt-dlp/discord.py, or before trusting a fix that touches real playback.
# Requires VERIFY_GUILD_ID / VERIFY_VOICE_CHANNEL_ID in .env (see below).
env -u PYTHONPATH python scripts/verify_playback.py
```

Note: on machines with ROS2 sourced into the shell (`PYTHONPATH` containing `/opt/ros/...`), plain `pytest`/`python` invocations can fail with an unrelated `ModuleNotFoundError: No module named 'lark'` from pytest's plugin autoload picking up ROS's `launch_testing` package. The `env -u PYTHONPATH` prefix above works around it.

Requires FFmpeg installed on the system and an Opus shared library available (bot.py probes common paths for `libopus.so.0/1` on Linux and Homebrew paths on macOS at startup).

### Required environment variables (`.env`, loaded via python-dotenv)

- `DISCORD_TOKEN` — required; bot exits at import time if missing.
- `YOUTUBE_API_KEY` — optional; without it, the YouTube-API fallback tier of `/recommend` is disabled (history-based recommendation tiers still work).
- `MINIMAX_API_KEY` — optional; without it, `/tts` responds with an error instead of failing at startup.
- `YTDLP_COOKIEFILE` — optional; path to a cookies.txt for yt-dlp to access login-gated sources.
- `MUSIC_DEBUG` — optional; `true/1/yes/on` enables verbose per-guild debug logging by default (can also be toggled per-guild at runtime via `/music_debug`).
- `VERIFY_GUILD_ID` / `VERIFY_VOICE_CHANNEL_ID` — optional; only needed to run `scripts/verify_playback.py` (the live playback smoke test). Must point at a real Discord test server / voice channel the bot is already a member of.
- `VERIFY_FIXTURE_URLS` — optional; comma-separated override for `scripts/verify_playback.py`'s built-in fixture YouTube URLs.

## Architecture

### Startup flow (`bot.py`)
- Loads `.env`, then attempts to load the Opus codec from a list of candidate library paths/names (voice playback silently breaks otherwise).
- `create_bot()` builds a fresh `commands.Bot` with an IPv4-forced `aiohttp.TCPConnector` (works around DNS/IPv6 issues) and syncs the slash-command tree in `on_ready`.
- `load_cogs()` dynamically loads every `.py` file in `cogs/` as an extension.
- `start_bot_with_retry()` wraps `bot.start()` in a manual retry loop with exponential backoff (capped at 60s), specifically to survive `ClientError`/`TimeoutError`/`GatewayNotFound`/stale-session `RuntimeError`s without crashing the process — discord.py's built-in reconnect is deliberately disabled (`reconnect=False`) because it has a known crash path in bad network conditions. A whole new `Bot` instance is created on each retry attempt.
- `database.setup_database()` runs once before the bot starts.

### Cog/View split
- `cogs/music.py` (`MusicCog`) owns essentially all playback state, keyed **per guild ID** in plain dicts on the cog instance: `queues`, `loop_modes`, `current_songs`, `player_messages`, `player_views`, `progress_tasks`, `volumes`, `disconnect_timers`, `playlist_enabled`, `voice_locks`, `session_songs`, `debug_modes`. There is no external state store — all of this lives in memory and is lost on restart (only play history is persisted, via `database.py`).
- `views/player_view.py` (`PlayerView`) renders the now-playing embed (progress bar, queue preview, requester) and defines the button interface (pause/resume, skip, loop-song, loop-queue, shuffle, recommend, stop). Button callbacks call back into the owning `MusicCog` instance passed at construction — the view and cog are tightly coupled by design.
- `views/settings_view.py` (`SettingsView`) is a minimal per-guild admin panel (currently just a playlist on/off toggle), also delegating state to `MusicCog`.
- `cogs/history.py` (`HistoryCog`) is read-only: queries `database.py` for user/server play history and renders embeds. No shared state with `MusicCog`.
- `cogs/tts.py` (`TTSCog`) is self-contained: calls the MiniMax `t2a_v2` REST API, writes the returned audio to a temp file, and plays it via `FFmpegPCMAudio` directly on the guild's voice client (does not go through the music queue).

### Playback pipeline (`MusicCog`)
- `ensure_voice_connection()` is the single choke point for joining/moving voice channels: uses a per-guild `asyncio.Lock`, handles same-channel reuse, cross-channel move, stale-client cleanup, and a bounded retry loop. It specifically detects Discord close code 4017 (DAVE E2EE requirement) and raises a `RuntimeError` with actionable instructions rather than retrying.
- `/play` uses two distinct yt-dlp configs: `YDL_OPTS_INFO_EXTRACT` (flat extraction, playlist-aware — used just to enqueue titles/URLs) vs `YDL_OPTS_STREAM` (`noplaylist=True`, resolves the actual audio stream URL — used lazily in `play_next` right before a track plays). Playlists are queued as lightweight entries and only resolved to a real stream URL when they're about to play.
- `play_next()` is the core state machine: re-queues the current song depending on loop mode (`SONG`/`QUEUE` push back onto the queue; `RECOMMEND` fetches a new song via `get_recommendation()` when the queue empties; `NONE` just stops), resolves the stream URL, builds FFmpeg options (`build_ffmpeg_options()` forwards yt-dlp's `http_headers`/User-Agent to reduce 403s), starts playback, logs the play to SQLite, and re-sends the player embed as a **new** message (deleting the old one) so it stays pinned to the bottom of the channel. The `after` playback callback re-enters `play_next()` via `asyncio.run_coroutine_threadsafe`, so this function is effectively re-entrant/recursive across track boundaries.
- `get_recommendation()` is tiered: (1) the requester's own top-played songs in this guild, (2) the guild's overall top-played songs, (3) YouTube Data API keyword search (by song title, since `relatedToVideoId` was deprecated in 2023) — each tier filtered against a dedup set built from the current queue, current song, and the guild's last 20 played tracks (by both video ID and a normalized/lowercased title, to catch re-uploads).
- Position tracking (`get_current_position`) is computed from `time.time()` deltas against a stored `start_time`/`resume_offset` per song, not queried from the voice client — pause/resume mutate these fields directly. `update_progress` re-renders the player embed on a 10s `tasks.loop`.
- Idle auto-disconnect: `start_disconnect_timer` schedules a 300s check; if nothing is playing/paused when it fires, the bot announces and calls `stop_and_leave`.

### Database (`database.py`)
- Plain `sqlite3` (no ORM), file at `./dc_bot.db` (gitignored), a fresh connection per call (`get_db_connection()`), `row_factory = sqlite3.Row`.
- Two tables: `songs` (deduped by unique `youtube_url`) and `play_history` (one row per play, FK to `songs`, stores `guild_id`/`user_id`/`played_at` epoch seconds).
- All read functions (`get_user_history`, `get_server_history`, `get_user_top_songs`, `get_guild_top_songs`, `get_recent_songs`) join through `songs` and are guild- and/or user-scoped — there is no cross-guild data leakage by construction, so preserve the `guild_id`/`user_id` filters when extending queries.

### Adding a new cog
Drop a new `.py` file in `cogs/` with a module-level `async def setup(bot): await bot.add_cog(YourCog(bot))` — `load_cogs()` picks it up automatically by filename, no registration elsewhere needed.

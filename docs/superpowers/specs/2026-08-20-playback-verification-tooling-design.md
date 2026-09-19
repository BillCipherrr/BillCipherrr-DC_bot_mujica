# Playback Verification Tooling — Design

## Purpose

This repo's playback pipeline (`cogs/music.py`) has had a string of regressions
around yt-dlp/JS-runtime resolution, 403s from YouTube, and race conditions in
`play_next` (see recent commits `3ca343c`, `e4e12ed`, `963fdaa`, and
`20260815_bug*.log`). There is currently no way to verify a fix (or a package
upgrade like `yt-dlp`) didn't reintroduce or shift one of these bugs without
manually running the live bot and eyeballing Discord.

This adds a two-layer verification tool so that after any change — code edit
or dependency upgrade — there's a fast, repeatable way to check that play,
pause, skip, and the recommendation system still work correctly.

## Scope

In scope:
- Layer A: an offline pytest suite covering `MusicCog`'s control-flow logic
  (state machine, locks/retry throttling, recommendation tiering/dedup,
  pause/resume/skip bookkeeping) with discord.py, yt-dlp, and the DB mocked
  or redirected to a temp file.
- Layer B: a standalone live smoke-test CLI script that connects to a real
  Discord test server and voice channel and drives play/pause/skip/recommend
  against real yt-dlp/YouTube, to catch regressions that only show up against
  the real network (403s, JS-runtime resolution, actual audio playback).
- New dev dependencies (`pytest`, `pytest-asyncio`) in a separate
  `requirements-dev.txt` (kept out of the bot's runtime `requirements.txt`).

Out of scope:
- CI wiring (this repo has no CI yet beyond the lint workflow spec; Layer B
  in particular cannot run in CI since it needs a real Discord bot token and
  a pre-existing test guild/voice channel — running it is a manual, local
  step).
- Testing `/tts` (`cogs/tts.py`) or `/history` (`cogs/history.py`) — user
  asked specifically about playback (play/pause/next/recommend) and package
  updates affecting it.
- Load/stress testing, multi-guild concurrency testing.

## Layer A — Offline logic test suite

### New files

```
tests/
  conftest.py                       # shared fakes + fixtures
  test_ytdlp_config.py              # pure-function tests
  test_play_next_state_machine.py
  test_retry_and_locks.py
  test_recommendation.py
  test_pause_resume_skip.py
requirements-dev.txt                # pytest, pytest-asyncio
```

### `conftest.py` — fakes

- `FakeVoiceClient`: tracks `is_playing()`/`is_paused()`/`is_connected()`,
  records calls to `play()`/`pause()`/`resume()`/`stop()`/`disconnect()`.
  `play(source, after)` stores the `after` callback so tests can invoke it
  manually to simulate track completion, and raises
  `discord.errors.ClientException("Already playing audio")` if called while
  already "in flight" (source of the race the last two fix commits address —
  see Layer A test list below) unless the caller explicitly stopped first.
  Optionally configurable to raise `ConnectionClosed(code=4017)` or
  `asyncio.TimeoutError` from `connect()`/`move_to()` to exercise
  `ensure_voice_connection`'s branches.
- `FakeInteraction` / `FakeGuild` / `FakeMember` / `FakeTextChannel`: minimal
  duck-typed stand-ins exposing exactly the attributes `MusicCog` and
  `PlayerView` touch (`.guild.id`, `.guild.voice_client`, `.user`,
  `.channel.send(...)` recording sent messages, `.response.defer()`,
  `.followup.send(...)`). `FakeTextChannel.send` appends to a list so
  assertions can check what the bot would have said (e.g. "連續多首歌曲播放失敗").
- `music_cog` fixture: constructs a real `MusicCog(bot=FakeBot())` — no
  patching of the class under test, only its collaborators.
- `temp_db` fixture: `monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")`
  then calls `database.setup_database()`, so recommendation/history tests hit
  a real (but throwaway) SQLite file — validates the actual SQL, not a mock
  of it.
- `patch_ytdlp` helper fixture: monkeypatches `yt_dlp.YoutubeDL` used inside
  `cogs.music` with a fake context manager whose `extract_info()` returns a
  caller-supplied canned dict (or raises, to simulate a 403/extraction
  failure) — no network access from Layer A, ever.

### Test coverage

- **`test_ytdlp_config.py`**: `_resolve_node_path()` prefers newest nvm path
  over `shutil.which`, falls back correctly when no nvm dir exists;
  `build_ffmpeg_options()` injects `-user_agent`/`-headers` from
  `http_headers` and leaves `before_options` intact when headers are absent;
  `normalize_youtube_url` (youtu.be → canonical), `extract_video_id`,
  `normalize_title_for_dedup`.
- **`test_play_next_state_machine.py`**: for each `LoopMode`
  (NONE/SONG/QUEUE/RECOMMEND) — correct requeue behavior of `current_song`;
  queue exhaustion sends "播放佇列已結束" and triggers `_send_session_summary`
  + `start_disconnect_timer`; RECOMMEND mode on empty queue calls
  `get_recommendation` and self-schedules another `play_next` via
  `asyncio.create_task`; `play_next` reconnects voice when
  `voice_client` is stale/disconnected and a member channel is available,
  and cleanly no-ops with a user message when it isn't.
- **`test_retry_and_locks.py`**:
  - `_retry_after_failure` increments `consecutive_play_failures` and stops
    (resets counter, message sent, `current_song` cleared) once
    `MAX_CONSECUTIVE_PLAY_FAILURES` is hit, otherwise sleeps
    `PLAY_FAILURE_RETRY_DELAY` and reschedules.
  - **Race regression test**: fire `_handle_after_playing(..., error=None)`
    (success path → calls `play_next` again) concurrently with a second,
    independent `play_next` call for the same guild (simulating the old bug
    where the `after` callback and an exception-triggered retry both fired).
    Assert `FakeVoiceClient.play()` is never entered re-entrantly — i.e. the
    per-guild `play_lock` actually serializes them. This directly encodes
    what commits `963fdaa`/`e4e12ed` fixed, so a regression fails loudly.
- **`test_recommendation.py`**: seed `temp_db` via real
  `database.log_song_play` calls, then assert tier ordering (user history →
  guild top → YouTube API, with `youtube` API client monkeypatched at
  `cogs.music.youtube`) and that candidates already in queue/current
  song/last-20-played (by video ID *and* normalized title) are excluded at
  each tier.
- **`test_pause_resume_skip.py`**: call
  `view.pause_resume_button.callback(view, fake_interaction)` directly
  against a `FakeVoiceClient` in playing/paused state; assert
  `paused_position`/`resume_offset`/`start_time` bookkeeping matches
  `get_current_position()` before and after; assert `skip_button` calls
  `vc.stop()` only when something is actually playing/paused.

Run with `pytest tests/` — seconds, no token, no network, no real DB touched.
This is the "run after every edit" loop.

## Layer B — Live smoke-test CLI

### New file: `scripts/verify_playback.py`

### Config (new `.env` vars, both required to run)

- `VERIFY_GUILD_ID` — test Discord server ID (bot must already be a member).
- `VERIFY_VOICE_CHANNEL_ID` — voice channel ID in that server for the bot to join.
- `VERIFY_FIXTURE_URLS` — optional comma-separated override for the two
  built-in fixture YouTube URLs (short, long-stable public videos), for when
  a hardcoded fixture eventually goes down.

Reuses `DISCORD_TOKEN`/`YOUTUBE_API_KEY`/`YTDLP_COOKIEFILE` already in `.env`.

### Flow

1. Boot a real `discord.Client`, wait for `on_ready`, construct a real
   `MusicCog(bot)` (same class Layer A tests, same class `bot.py` loads).
2. Join `VERIFY_VOICE_CHANNEL_ID` via the real `ensure_voice_connection`.
3. Build a `LiveInteraction` — same shim shape as Layer A's `FakeInteraction`,
   but wrapping the *real* `discord.Guild`/`TextChannel`/`Member`/
   `VoiceClient` objects from the live gateway connection; `.response`/
   `.followup` are stubbed to print to stdout instead of requiring an actual
   slash-command round-trip. This keeps `MusicCog`'s public methods
   (`play_next`, `get_recommendation`, etc.) callable identically from tests
   and from this script — no method needs a Discord interaction to exist.
4. Run the fixed scenario, printing a `[STEP] ... PASS/FAIL` line per step
   and logging enough detail to diagnose a failure without re-running:
   - **Play**: enqueue fixture #1, call `play_next`, poll
     `vc.is_playing()` up to a timeout. Fail with the yt-dlp exception text
     if extraction raised, or "no audio started" if it never called `play()`.
     Explicitly log whether `_resolve_node_path()` found a real node path —
     a `None` here is itself a warning even if playback happens to succeed,
     since it means the bot silently fell back to the 403-prone client.
   - **Pause/Resume**: pause, assert `is_paused()` and that
     `get_current_position()` doesn't advance across a short sleep; resume,
     assert it advances again.
   - **Skip**: enqueue fixture #2, call `vc.stop()`, poll for the
     `after_playing` callback to have driven `play_next` into playing
     fixture #2 (title match) within a timeout.
   - **Recommend**: set `LoopMode.RECOMMEND`, let the queue drain, assert
     `get_recommendation` returns a track and playback continues
     automatically (checks real DB/YouTube-API tiering end to end, not just
     the logic — this is the one Layer A structurally can't cover for the
     "does the real fallback tier actually find something" question).
   - Wait for a track's `after_playing` naturally at least once during the
     run (not synthetically triggered) so the real `voice_client.play(...,
     after=...)` wiring itself is exercised, not just the logic it calls.
5. `finally`: always `stop_and_leave` and disconnect, even on failure, so a
   crashed run doesn't strand the bot in the voice channel.
6. Exit code `0` if every step passed, `1` otherwise — usable as
   `pip install -U yt-dlp && python scripts/verify_playback.py`.

### Error handling

Each step is wrapped individually; one step failing doesn't abort the rest
(e.g. if Play fails, still attempt cleanup and report Pause/Skip/Recommend as
`SKIPPED` rather than crash the script) so a single run tells you the full
state of the system, not just the first broken thing.

### Testing

- Layer A is self-verifying (it's a test suite).
- Layer B is verified by running it once against the real, currently-working
  bot (this session, after implementation) to confirm the harness itself is
  correct, then intentionally breaking something small (e.g. temporarily
  pointing `_NODE_PATH` at a bogus path) to confirm the script actually
  fails loudly rather than false-passing.

## Day-to-day usage

- After any code change to `cogs/music.py`/`views/player_view.py`/`database.py`:
  `pytest tests/` (seconds).
- After a dependency upgrade (`yt-dlp`, `discord.py`, etc.) or before trusting
  a fix that touches real playback: `python scripts/verify_playback.py`
  (needs the bot online in a real test server/channel, takes a minute or two).

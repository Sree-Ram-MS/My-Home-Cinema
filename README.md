# CastFlix prototype — phone media server

One Python file, no extra packages. The phone serves a Netflix-like page
over home Wi-Fi. The TV browser opens it by IP and plays the original
file — no casting, no re-encoding, no pendrive.

## v0.7 — Offline redirect to CineLite (2026-10-28)

Yes, with one hard limit (see below). Added to the Online tab:

- Tick **Auto-redirect to CineLite when this server goes offline**.
  CastFlix then checks `/api/status` every 10 seconds while the
  page is open. After 2 failed checks, it shows a Server offline
  screen and, if the tick is on, counts down 10 seconds and then
  opens https://cinelite.xyz/ automatically. Tap Stay Here to
  cancel (it pauses the check for 5 minutes), Try Again to retest
  the phone, or Open CineLite to go immediately.
- There is also an **Open cinelite.xyz now** button in the Online
  tab, for manual use any time.
- The check is paused while the Online iframe player is open, so
  going offline on the phone does not kick you out of an online
  stream that does not need the phone.

**Hard limit:** this only works if the CastFlix page was already
open when the server went down. If you type the IP:port address
after the server is already down, the browser cannot load any
page at all, so no code can redirect it. For that case, bookmark
https://cinelite.xyz/ directly on the TV, or use the standalone
hosted Online page from v0.5, which needs no phone at all.

## v0.6 — Online tab layout fix (2026-10-28)

Fixed from a screenshot of the Online tab on a wide screen:

- The Online card was limited to 920px with no centring, so on a
  wide TV/desktop it sat on the left with a large empty black area
  on the right. It now fills the full width like the local rows.
- Header state was confusing: All stayed white/active while
  Online was ON. Online now clears the local tab highlight, and
  returning to Movies/Series restores it.
- The local library search box is now hidden while Online is on,
  so it no longer looks like it should search online titles.
- Save API Key button height now matches its input field.

## v0.5 — Search by name + standalone Online page (2026-10-28)

**Search by name (Online tab only):**
Search needs a free TMDB API key, saved only on the TV browser —
it is never sent to the phone server, because the search runs
directly from the TV browser to TMDB. Get it free: themoviedb.org
account → Settings → API → API Key (v3). Paste it in the Online
tab, tap Save, type a movie/show name, tap Search, then tap a
result to play it. Anime still needs an AniList ID, as before.

**Works even if the phone terminal is closed:**
No — not for the main CastFlix page. That page is served by the
phone, so closing the terminal stops new loads and stops local
files. But the Online player itself loads directly from the
internet, so a player already open on the TV can keep playing
until you reload or close it.
For a version that works any time with no phone at all, use the
new standalone file `online.html`:
1. Upload it as `index.html` to a free static host — a new GitHub
   repo with Pages enabled, Netlify Drop, or Cloudflare Pages.
2. Open that hosted URL on the TV any time. It needs internet,
   and it only has the Online tab — local phone files will not
   work from the hosted page.

## v0.4 — Online CineLite tab (2026-10-28)

Local library is unchanged. Tap **🌐 Online** in the header for a
separate tab:

- Choose Movie (TMDB ID), TV Show (TMDB ID + season + episode),
  or Anime (AniList ID + episode).
- Pick an accent colour, preferred quality, start/resume time,
  pause recommendations, and start-from-0.
- Play opens the CineLite iframe player full-screen, with an Exit
  button. The player can also send its Continue Watching progress
  back to CastFlix, which saves it on the TV browser and resumes
  the same title next time (unless you tick start-from-0).
- Try-it buttons: Interstellar, Fight Club, Game of Thrones S1E1,
  Arcane S1E1. Recent online titles are kept on the TV browser.
- Important: Online does **not** play files from your phone. The
  phone only serves this page; the TV loads CineLite directly from
  the internet, so the TV needs internet for this tab, and playback
  depends on that external service. Find TMDB IDs on themoviedb.org.

## v0.3 — Stylish UI (2026-10-28)

Same server, same features, new look — no function removed:

- Hero banner at the top: Continue Watching first, otherwise the
  first movie/series, with a big title, Play and More Info buttons.
  If the title has a `poster.jpg`, it becomes the hero backdrop.
- Horizontal Netflix-style rows instead of a plain grid, with
  scroll-snap, hidden scrollbars, and cards that lift and show a
  play button on hover/focus.
- Glass-style sticky header, pill search and pill tabs, 2:3 poster
  cards with rounded corners, shadows and gradient fallbacks when
  there is no poster. Posters are no longer covered by a big title.
- TV mode still works exactly as in v0.2: `?tv=1`, arrows/OK/Back,
  10-second skip, on-screen TV controls, auto next episode.
  Focused cards now scroll themselves into view in a row.

## v0.2 — UI fixes (2026-10-28)

Fixed after comparing with the HomeFlix projects linked below:

- Posters no longer overflow their cards (the old padding + `height: 100%`
  image could push the card layout apart).
- Titles with an apostrophe, like `Schindler's List`, no longer break
  the page. Clicks now use data attributes instead of titles embedded
  in `onclick="..."` JavaScript strings.
- Continue Watching actually shows now. The old code saved progress to
  localStorage but never read it back into the cards.
- TV mode: tap **TV mode**, or add `?tv=1` to the address once and the
  TV remembers it. Cards get bigger, focus is visible, and the remote
  works: arrows move, OK opens, Back closes, Left/Right skip 10 seconds
  while playing, and the next episode plays automatically.
- Closing the player no longer jumps you back to the top of the page.
- If the library fails to load, the page now says so instead of
  staying blank.
- Cards, episode buttons and player buttons are real focusable
  buttons now, not `div onclick`, so a TV remote can actually land on them.

Reference ideas only — no code copied: kprakz/homeflix (TV remote
mode, Continue Watching, auto next episode, MKV handling) and
azad25/homeflix-wifi (TMDB-style posters with gradient fallback,
smart categorisation, responsive grid, Continue Watching).

## What it does

- Scans a folder for movies and series
- Shows a dark grid UI with search, Movies / Series tabs, and posters
  (put a `poster.jpg` next to a movie, or in a series episode folder)
- Groups series as `Show / Season 1 / Show S01E01.mp4`
- Plays video in the TV browser, with seeking (HTTP Range support)
- Remembers where you stopped, in the TV browser
- Serves `.srt` subtitles as WebVTT, and `.vtt` directly
- Flags MKV / AVI / etc. as "may not play in TV browser" — MP4 is safest
- Optional PIN: `python3 server.py --media ./media --pin 1234`

## Folder layout

```
media/
  Movies/
    Avatar (2009)/
      Avatar (2009).mp4
      poster.jpg
  Series/
    Demo Show/
      Season 1/
        Demo Show S01E01.mp4
        Demo Show S01E02.mp4
```

## Test on a PC first (2 minutes, recommended)

```bash
python3 server.py --media ./media --port 8000
```

Open `http://127.0.0.1:8000` on the PC, then open the LAN address
printed by the server (for example `http://192.168.1.10:8000`) in the
TV browser. If the TV browser plays and seeks, your STB browser works.

## Run on an Android phone with Termux

1. Install Termux from F-Droid (the Play Store version is outdated).
2. Copy `server.py` and your media folder to the phone.
   In Termux, allow storage access once: `termux-setup-storage`
   Your downloads are usually under `~/storage/downloads/`.
3. In Termux:

```bash
pkg install python -y
cd ~/storage/downloads/CastFlix
python3 server.py --media ~/storage/downloads/Movies --port 8000
```

4. The server prints a TV address like `http://192.168.1.10:8000`.
   Open that in the Jio STB browser. Phone and TV must be on the
   same Wi-Fi.
5. Keep the phone awake, on Wi-Fi, and charging while watching.
   In Android settings, turn off battery optimisation for Termux
   if the server stops when the screen locks.

## If a file won't play on the TV

- First try the same file as MP4 (H.264 + AAC).
- MKV files often need remuxing, not re-encoding, for example:

```bash
ffmpeg -i input.mkv -c copy output.mp4
```

  This keeps the quality and usually just changes the container.
- If the audio is DTS and the browser is silent, that file needs an
  audio transcode — that is a job for the later Jellyfin server,
  not this prototype.

## Stop

Press Ctrl+C in Termux / the terminal.

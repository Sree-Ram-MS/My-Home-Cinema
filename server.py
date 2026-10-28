#!/usr/bin/env python3
"""
CastFlix prototype - phone media server with a Netflix-like TV browser UI.

Pure Python standard library only. No pip packages needed.

Run:
    python3 server.py --media ./media --port 8000
    python3 server.py --media /path/to/movies --port 8000 --pin 1234

Then on the TV browser (same Wi-Fi) open:
    http://<phone-ip>:8000

Folder layout that works best:
    media/
      Movies/
        Avatar (2009)/
          Avatar (2009).mp4
          poster.jpg            (optional)
      Series/
        Demo Show/
          Season 1/
            Demo Show S01E01.mp4
            Demo Show S01E02.mp4

Notes:
- MP4 + H.264 + AAC plays in almost every TV browser.
  MKV / HEVC / DTS may not play in a browser even if the TV hardware
  supports them - the UI flags those files so you know.
- Seeking works because /stream supports HTTP Range requests.
- Continue-watching is saved in the TV browser's localStorage.
- If --pin is set, the library/stream needs that PIN once per browser.
  This is LAN-only convenience protection, not strong security.
"""

import argparse
import hashlib
import html
import json
import mimetypes
import os
import re
import socket
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts"}
BROWSER_FRIENDLY = {".mp4", ".webm"}
POSTER_NAMES = {"poster.jpg", "poster.jpeg", "poster.png", "cover.jpg",
                "cover.jpeg", "cover.png", "folder.jpg", "folder.png"}
GENERIC_FOLDERS = {"movies", "movie", "series", "shows", "tv", "videos",
                   "video", "media", "downloads", "download"}
QUALITY_TAGS = re.compile(
    r"\b(2160p|1080p|720p|480p|4k|web-dl|webdl|bluray|blu-ray|hdrip|"
    r"brrip|x264|x265|h\.?264|h\.?265|hevc|aac|ac3|dts|10bit|8bit|"
    r"proper|repack|extended|remux)\b", re.I)
YEAR_RE = re.compile(r"\b(19\d\d|20\d\d)\b")
SEASON_EP_RE = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,2})")
SEASON_FOLDER_RE = re.compile(r"season\s*(\d+)", re.I)


def clean_title(raw):
    """Turn 'Avatar.2009.1080p.WEB-DL.x264' into 'Avatar'."""
    text = raw or ""
    text = QUALITY_TAGS.sub(" ", text)
    text = re.sub(r"[\._\-]+", " ", text)
    text = re.sub(r"\[.*?\]|\(.*?\)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_year(text):
    m = YEAR_RE.search(text or "")
    return int(m.group(1)) if m else None


def find_poster(folder, stem):
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        low = name.lower()
        if low in POSTER_NAMES:
            return os.path.join(folder, name)
    for ext in (".jpg", ".jpeg", ".png"):
        p = os.path.join(folder, stem + ext)
        if os.path.exists(p):
            return p
    return None


def find_subtitles(folder, stem):
    out = {}
    for ext in (".vtt", ".srt"):
        p = os.path.join(folder, stem + ext)
        if os.path.exists(p):
            out[ext[1:]] = p
    return out


def scan_library(root):
    movies = []
    series_map = {}
    by_id = {}

    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            stem, ext = os.path.splitext(name)
            ext = ext.lower()
            if ext not in VIDEO_EXTS:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            parts = [p for p in os.path.dirname(rel).split(os.sep) if p not in ("", ".")]
            file_id = hashlib.sha1(rel.encode()).hexdigest()[:12]
            poster = find_poster(dirpath, stem)
            subs = find_subtitles(dirpath, stem)

            season_ep = SEASON_EP_RE.search(stem)
            season_folder = None
            for part in parts:
                m = SEASON_FOLDER_RE.search(part)
                if m:
                    season_folder = int(m.group(1))
                    break

            if season_ep or season_folder is not None:
                season = int(season_ep.group(1)) if season_ep else season_folder
                episode = int(season_ep.group(2)) if season_ep else 0
                if season_folder is not None and len(parts) >= 2:
                    show_raw = parts[-2]
                elif season_ep:
                    show_raw = stem[:season_ep.start()]
                elif parts:
                    show_raw = parts[0]
                else:
                    show_raw = stem
                show_title = clean_title(show_raw) or "Unknown Series"
                show_id = hashlib.sha1(show_title.lower().encode()).hexdigest()[:12]
                ep = {
                    "id": file_id, "title": f"S{season:02d}E{episode:02d}",
                    "season": season, "episode": episode,
                    "file": name, "size": os.path.getsize(full), "ext": ext,
                    "browser_friendly": ext in BROWSER_FRIENDLY,
                    "has_subtitles": bool(subs),
                }
                entry = series_map.get(show_id)
                if entry is None:
                    entry = {"id": show_id, "title": show_title,
                             "year": extract_year(show_raw),
                             "poster_url": f"/poster?id={show_id}" if poster else None,
                             "episodes": []}
                    series_map[show_id] = entry
                    if poster:
                        by_id[show_id] = {"poster": poster}
                entry["episodes"].append(ep)
                by_id[file_id] = {"path": full, "subs": subs}
                if poster and show_id not in by_id:
                    by_id[show_id] = {"poster": poster}
                continue

            # Movie: prefer its own folder name, unless that folder is generic.
            if parts and parts[-1].lower() not in GENERIC_FOLDERS:
                movie_raw = parts[-1]
            else:
                movie_raw = stem
            title = clean_title(movie_raw) or clean_title(stem) or "Unknown"
            item = {
                "id": file_id, "title": title, "year": extract_year(movie_raw) or extract_year(stem),
                "file": name, "size": os.path.getsize(full), "ext": ext,
                "browser_friendly": ext in BROWSER_FRIENDLY,
                "has_subtitles": bool(subs),
                "poster_url": f"/poster?id={file_id}" if poster else None,
            }
            movies.append(item)
            by_id[file_id] = {"path": full, "subs": subs}
            if poster:
                by_id[file_id]["poster"] = poster

    movies.sort(key=lambda x: x["title"].lower())
    series = sorted(series_map.values(), key=lambda x: x["title"].lower())
    for s in series:
        s["episodes"].sort(key=lambda e: (e["season"], e["episode"]))
    return {"movies": movies, "series": series}, by_id


def srt_to_vtt(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    # SRT timestamps use commas, WebVTT uses dots.
    text = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text)
    return "WEBVTT\n\n" + text.lstrip("\ufeff")


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


HTML = r"""
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CastFlix</title>
<style>
:root{--bg:#07070c;--panel:#14141d;--panel2:#1d1d2a;--line:#2a2a3a;
--text:#fff;--muted:#a9a9bd;--red:#e50914;--red2:#ff2d3f;--radius:16px}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
-webkit-font-smoothing:antialiased}
header{position:sticky;top:0;z-index:10;display:flex;gap:14px;align-items:center;
flex-wrap:wrap;padding:14px 28px;border-bottom:1px solid rgba(255,255,255,.08);
background:linear-gradient(180deg,rgba(7,7,12,.96),rgba(7,7,12,.75));
backdrop-filter:blur(16px)}
.logo{font-size:30px;font-weight:950;letter-spacing:1.5px;line-height:1;
background:linear-gradient(90deg,#ff2d3f,#ff7a18);-webkit-background-clip:text;
background-clip:text;color:transparent}
.logo small{display:block;font-size:10px;letter-spacing:4px;color:var(--muted);
background:none;-webkit-text-fill-color:var(--muted)}
input[type=search]{flex:1;min-width:210px;max-width:440px;padding:11px 18px;
border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.07);
color:#fff;font-size:16px;outline:none}
input[type=search]:focus{border-color:#fff;background:rgba(255,255,255,.12)}
.tabs{display:flex;gap:6px;background:rgba(255,255,255,.07);padding:4px;border-radius:999px}
.tabs button,.tvBtn{background:transparent;color:#ddd;border:0;padding:9px 17px;
border-radius:999px;cursor:pointer;font-size:15px;font-weight:650}
.tabs button.active{background:#fff;color:#000}
.tvBtn{border:1px solid var(--line);background:rgba(255,255,255,.07)}
.tvBtn.on{background:var(--red);color:#fff;border-color:var(--red)}
button:focus-visible,input:focus-visible{outline:3px solid #fff;outline-offset:3px}
.hero{position:relative;min-height:54vh;display:flex;align-items:flex-end;overflow:hidden}
.heroBg{position:absolute;inset:0}
.heroBg img{width:100%;height:100%;object-fit:cover;object-position:center 22%}
.heroShade{position:absolute;inset:0;
background:linear-gradient(90deg,rgba(7,7,12,.97) 0%,rgba(7,7,12,.55) 48%,rgba(7,7,12,.12) 100%),
linear-gradient(0deg,var(--bg) 0%,transparent 58%)}
.heroContent{position:relative;padding:56px 32px 36px;max-width:680px}
.heroEyebrow{color:#ff8a94;font-weight:800;letter-spacing:3px;font-size:13px;text-transform:uppercase}
.heroTitle{margin:10px 0 12px;font-size:clamp(38px,6.5vw,68px);line-height:.95;
font-weight:950;letter-spacing:-1.5px;text-shadow:0 4px 30px rgba(0,0,0,.6)}
.heroMeta{color:#d6d6e2;font-size:16px}
.heroBtns{display:flex;gap:12px;margin-top:22px;flex-wrap:wrap}
.btnPlay,.btnInfo{border:0;border-radius:12px;padding:15px 28px;font-size:17px;
font-weight:850;cursor:pointer}
.btnPlay{background:#fff;color:#000}
.btnInfo{background:rgba(255,255,255,.16);color:#fff;border:1px solid rgba(255,255,255,.28);
backdrop-filter:blur(10px)}
.btnPlay:hover,.btnInfo:hover{transform:translateY(-1px)}
main{padding:8px 28px 64px}
h2{margin:30px 0 14px;font-size:23px;font-weight:850;letter-spacing:-.3px}
h2::before{content:"";display:inline-block;width:5px;height:20px;border-radius:4px;
background:linear-gradient(180deg,var(--red2),#ff7a18);margin-right:11px;vertical-align:-3px}
.row{display:flex;gap:16px;overflow-x:auto;padding:6px 2px 18px;
scroll-snap-type:x proximity;scrollbar-width:none}
.row::-webkit-scrollbar{display:none}
.card{flex:0 0 188px;background:var(--panel);border-radius:var(--radius);
overflow:hidden;cursor:pointer;border:1px solid rgba(255,255,255,.08);
color:#fff;text-align:left;padding:0;font:inherit;scroll-snap-align:start;
box-shadow:0 10px 30px rgba(0,0,0,.35);transition:transform .22s ease,box-shadow .22s ease,outline-color .15s}
.card:hover,.card:focus-visible{transform:translateY(-5px) scale(1.02);
box-shadow:0 18px 40px rgba(0,0,0,.55);outline:3px solid #fff;outline-offset:1px}
.poster{position:relative;aspect-ratio:2/3;overflow:hidden;
background:linear-gradient(135deg,#e50914,#3b0a5e 60%,#111)}
.poster img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block}
.poster .titleOverlay{position:absolute;left:0;right:0;bottom:0;
padding:36px 14px 14px;background:linear-gradient(transparent,rgba(0,0,0,.9));
font-size:24px;font-weight:850;line-height:1.1}
.playIcon{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%) scale(.8);
width:56px;height:56px;border-radius:50%;background:rgba(255,255,255,.94);color:#000;
display:flex;align-items:center;justify-content:center;font-size:22px;opacity:0;
transition:opacity .2s,transform .2s;box-shadow:0 8px 24px rgba(0,0,0,.5)}
.card:hover .playIcon,.card:focus-visible .playIcon{opacity:1;transform:translate(-50%,-50%) scale(1)}
.meta{padding:12px 13px 14px} .meta b{display:block;font-size:15px;line-height:1.25}
.meta small{color:var(--muted)}
.meta .ext{display:inline-block;margin-top:7px;background:rgba(255,255,255,.1);
border:1px solid rgba(255,255,255,.14);color:#e8e8f2;font-size:11px;font-weight:750;
letter-spacing:.5px;padding:3px 7px;border-radius:6px}
.badge{display:inline-block;margin-top:7px;background:#7a5a00;color:#fff;
font-size:12px;padding:3px 7px;border-radius:6px}
.progress{height:5px;background:#333;margin-top:10px;border-radius:4px;overflow:hidden}
.progress i{display:block;height:100%;background:linear-gradient(90deg,var(--red2),#ff7a18)}
#player,#seriesModal{position:fixed;inset:0;background:#000;z-index:20;display:none;
flex-direction:column} #player.show,#seriesModal.show{display:flex}
#player video{width:100%;flex:1;background:#000;min-height:0}
.playerTop,.modalTop{padding:14px 20px;display:flex;justify-content:space-between;
align-items:center;background:rgba(20,20,30,.95);gap:12px} button.close{background:var(--red);
color:#fff;border:0;padding:10px 18px;border-radius:10px;cursor:pointer;font-size:15px;font-weight:700}
.tvbar{display:none;gap:10px;padding:14px 20px;background:#111;flex-wrap:wrap}
body.tv .tvbar{display:flex}
.tvbar button{background:#222;color:#fff;border:1px solid #444;padding:12px 20px;
border-radius:12px;cursor:pointer;font-size:16px}
#seriesModal{background:#0c0c14}
.epList{padding:20px;overflow:auto;display:grid;gap:11px;max-width:900px;width:100%;margin:0 auto}
.epList button{text-align:left;background:var(--panel);color:#fff;border:1px solid var(--line);
padding:15px 18px;border-radius:14px;cursor:pointer;font-size:16px;display:flex;
justify-content:space-between;align-items:center;gap:12px}
.epList button:hover,.epList button:focus-visible{border-color:#fff}
#lock{position:fixed;inset:0;background:radial-gradient(600px 400px at 50% 30%,#3b0a1e,var(--bg));
z-index:30;display:none;align-items:center;justify-content:center} #lock.show{display:flex}
.lockBox{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);
padding:32px;border-radius:22px;text-align:center;backdrop-filter:blur(14px)}
.lockBox input{padding:12px 16px;font-size:17px;border-radius:12px;border:1px solid #444;
background:#111;color:#fff} .lockBox button{margin-top:14px;background:var(--red);
color:#fff;border:0;padding:12px 22px;border-radius:12px;font-size:16px;cursor:pointer;font-weight:750}
.note{color:var(--muted);font-size:14px;line-height:1.6}
body.tv .card{flex-basis:238px}
body.tv .hero{min-height:60vh}
body.tv .tabs button,body.tv .tvBtn{font-size:18px;padding:12px 20px}
@media (max-width:640px){
 header,main{padding-left:16px;padding-right:16px}
 .hero{min-height:46vh} .heroContent{padding:40px 18px 26px}
 .card{flex-basis:152px}
}
#onlineSection{display:none;padding:8px 28px 64px;width:100%}
#onlineSection.show{display:block}
.onlineCard{width:100%}
body.online #q{display:none}
body.online .tabs button.active{background:transparent;color:#ddd}
@media (max-width:640px){#onlineSection{padding:8px 16px 48px}}
.onlineCard{background:var(--panel);border:1px solid var(--line);border-radius:22px;padding:24px}
.formGrid{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:start}
#tmdbSaveBtn{margin-top:0;padding:12px 26px;height:48px;display:flex;align-items:center;justify-content:center}
.field label{display:block;color:var(--muted);font-size:13px;margin-bottom:6px;font-weight:700}
.field input,.field select{width:100%;padding:12px 14px;border-radius:12px;border:1px solid var(--line);
background:#0e0e16;color:#fff;font-size:16px}
.field.full{grid-column:1/-1}
.presetRow{display:flex;gap:8px;flex-wrap:wrap}
.presetBtn{width:38px;height:38px;border-radius:50%;border:3px solid transparent;cursor:pointer}
.presetBtn.on{border-color:#fff}
.chipRow{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}
.chipRow button{background:rgba(255,255,255,.09);color:#fff;border:1px solid var(--line);
padding:10px 16px;border-radius:999px;cursor:pointer;font-size:15px}
.checkRow{display:flex;gap:18px;flex-wrap:wrap;margin-top:14px;color:#ddd}
.checkRow label{display:flex;gap:8px;align-items:center}
#onlineUrl{word-break:break-all;background:#0e0e16;border:1px solid var(--line);
border-radius:12px;padding:12px 14px;margin-top:14px;color:#c9c9dd;font-size:14px}
#onlinePlayer{position:fixed;inset:0;background:#000;z-index:25;display:none;flex-direction:column}
#onlinePlayer.show{display:flex}
#onlinePlayer iframe{width:100%;flex:1;border:0;background:#000}
#offlineOverlay{position:fixed;inset:0;background:rgba(0,0,0,.94);z-index:60;display:none;align-items:center;justify-content:center;text-align:center;padding:24px}
#offlineOverlay.show{display:flex}
.offlineBox{background:var(--panel);border:1px solid var(--line);border-radius:22px;padding:32px;max-width:560px;width:100%}
.searchGrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-top:12px}
.searchCard{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden;color:#fff;text-align:left;padding:0;cursor:pointer;font:inherit}
.searchCard img{width:100%;aspect-ratio:2/3;object-fit:cover;display:block}
.searchCard .searchNoPoster{aspect-ratio:2/3;display:flex;align-items:center;padding:14px;background:linear-gradient(135deg,#e50914,#3b0a5e);font-weight:800}
.searchCard span{display:block;padding:10px 12px}
.searchCard small{display:block;color:var(--muted);margin-top:4px}
@media (max-width:640px){.formGrid{grid-template-columns:1fr}}
</style></head><body>
<header><div class="logo">CASTFLIX<small>HOME CINEMA</small></div>
<input id="q" type="search" placeholder="🔍 Search movies and series...">
<div class="tabs"><button type="button" data-tab="all" class="active">All</button>
<button type="button" data-tab="movies">Movies</button><button type="button" data-tab="series">Series</button></div>
<button type="button" id="tvBtn" class="tvBtn">TV mode</button>
<button type="button" id="onlineBtn" class="tvBtn">🌐 Online</button></header>
<section class="hero" id="hero" style="display:none"><div class="heroBg" id="heroBg"></div>
<div class="heroShade"></div><div class="heroContent">
<div class="heroEyebrow" id="heroEyebrow">Featured</div>
<div class="heroTitle" id="heroTitle"></div>
<div class="heroMeta" id="heroMeta"></div>
<div class="heroBtns"><button type="button" class="btnPlay heroBtn" id="heroPlayBtn">▶ Play</button>
<button type="button" class="btnInfo heroBtn" id="heroInfoBtn">ℹ More Info</button></div>
</div></section>
<main id="mainLocal">
<p class="note" id="status">Loading your library...</p>
<h2 id="hContinue" style="display:none">Continue Watching</h2><div class="row" id="continue"></div>
<h2 id="hMovies">Movies</h2><div class="row" id="movies"></div>
<h2 id="hSeries">Series</h2><div class="row" id="series"></div>
<p class="note">Tip: keep the phone on Wi-Fi, awake and charging while you watch.
MP4 files play in almost every TV browser. MKV files are flagged because some TV browsers refuse them.
On a TV remote: arrows move, OK opens, Back closes, and while playing Left/Right skip 10 seconds.</p>
</main>
<section id="onlineSection"><div class="onlineCard">
<h2 style="margin-top:0">Online — CineLite embed</h2>
<p class="note">This tab does <b style="color:#fff">not</b> play files from your phone. Your phone only serves this page — the TV loads the CineLite player directly from the internet, by TMDB / AniList ID. If a title will not play here, use your local copy in Movies / Series instead. The TV needs internet for this tab.</p>
<h3>Search by name</h3>
<p class="note">Search needs a free TMDB API key, saved only on this TV browser. Get it free: create an account on themoviedb.org, go to Settings &gt; API, copy the API Key (v3), paste it here and tap Save. Without a key, use the ID form below.</p>
<div class="formGrid">
<div class="field"><label>TMDB API key (saved on this browser only)</label>
<input id="tmdbKey" type="password" placeholder="Paste your TMDB API key here"></div>
<div class="field"><label>&nbsp;</label><button type="button" class="btnInfo onlineBtn" id="tmdbSaveBtn" style="width:100%">Save API Key</button></div>
<div class="field full"><label>Movie or show name</label>
<input id="onSearchName" placeholder="e.g. Interstellar"></div>
</div>
<div class="heroBtns"><button type="button" class="btnPlay onlineBtn" id="onSearchBtn">🔍 Search by Name</button></div>
<p class="note" id="tmdbKeyStatus"></p>
<p class="note" id="onSearchErr" style="color:#ff8a94"></p>
<div class="searchGrid" id="onSearchResults"></div>
<h3>Or play by ID</h3>
<div class="formGrid">
<div class="field"><label>Media type</label>
<select id="onType"><option value="movie">Movie — TMDB ID</option><option value="tv">TV Show — TMDB ID</option><option value="anime">Anime — AniList ID</option></select></div>
<div class="field"><label id="onIdLabel">TMDB ID</label>
<input id="onId" inputmode="numeric" placeholder="e.g. 157336"></div>
<div class="field" id="onSeasonField" style="display:none"><label>Season</label>
<input id="onSeason" inputmode="numeric" value="1"></div>
<div class="field" id="onEpisodeField" style="display:none"><label>Episode</label>
<input id="onEpisode" inputmode="numeric" value="1"></div>
<div class="field"><label>Preferred quality</label>
<select id="onQuality"><option value="">Auto / 1080p</option><option value="4k">4K UHD</option><option value="1080p">1080p</option><option value="720p">720p</option><option value="480p">480p</option></select></div>
<div class="field"><label>Start / resume time</label>
<input id="onStart" placeholder="Leave blank to resume, or 120 / 02:30"></div>
</div>
<div class="field" style="margin-top:14px"><label>Accent colour</label>
<div class="presetRow" id="presetRow">
<button type="button" class="presetBtn on" data-color="e50914" style="background:#e50914" title="Crimson"></button>
<button type="button" class="presetBtn" data-color="00e5ff" style="background:#00e5ff" title="Cyan"></button>
<button type="button" class="presetBtn" data-color="10b981" style="background:#10b981" title="Emerald"></button>
<button type="button" class="presetBtn" data-color="a855f7" style="background:#a855f7" title="Purple"></button>
<button type="button" class="presetBtn" data-color="f59e0b" style="background:#f59e0b" title="Gold"></button>
<button type="button" class="presetBtn" data-color="3b82f6" style="background:#3b82f6" title="Blue"></button>
<button type="button" class="presetBtn" data-color="fb7185" style="background:#fb7185" title="Rose"></button>
<button type="button" class="presetBtn" data-color="f97316" style="background:#f97316" title="Orange"></button>
</div>
<input id="onColor" value="e50914" style="margin-top:10px;max-width:220px;padding:11px 14px;border-radius:12px;border:1px solid var(--line);background:#0e0e16;color:#fff"></div>
<div class="checkRow"><label><input type="checkbox" id="onSuggest"> Pause recommendations</label>
<label><input type="checkbox" id="onReset"> Start from 0:00 (clear saved progress)</label></div>
<div class="heroBtns"><button type="button" class="btnPlay onlineBtn" id="onlinePlayBtn">▶ Play Online</button>
<button type="button" class="btnInfo onlineBtn" id="onlineCopyBtn">Copy Link</button></div>
<div id="onlineUrl"></div>
<p class="note" id="onlineErr" style="color:#ff8a94"></p>
<h3>Try these</h3>
<div class="chipRow">
<button type="button" class="featBtn onlineBtn" data-type="movie" data-id="157336" data-title="Interstellar">Interstellar</button>
<button type="button" class="featBtn onlineBtn" data-type="movie" data-id="550" data-title="Fight Club">Fight Club</button>
<button type="button" class="featBtn onlineBtn" data-type="tv" data-id="1399" data-season="1" data-episode="1" data-title="Game of Thrones S1E1">Game of Thrones S1E1</button>
<button type="button" class="featBtn onlineBtn" data-type="tv" data-id="94605" data-season="1" data-episode="1" data-title="Arcane S1E1">Arcane S1E1</button>
</div>
<h3>Recent online</h3>
<div class="chipRow" id="onlineRecent"><span class="note">Nothing played online yet on this browser.</span></div>
<h3>If the phone server goes offline</h3>
<div class="checkRow"><label><input type="checkbox" id="offlineRedirectToggle"> Auto-redirect to CineLite when this server goes offline (10 second countdown, you can cancel)</label></div>
<p class="note">This works only if this CastFlix page was already open when the server went down — CastFlix checks the server every 10 seconds in the background. If you open the IP:port address <i>after</i> the server is already down, the browser cannot load this page at all, so it cannot redirect. For that case, bookmark https://cinelite.xyz/ directly on the TV, or use the standalone hosted Online page.</p>
<div class="heroBtns"><button type="button" class="btnInfo onlineBtn" id="goCineliteBtn">Open cinelite.xyz now</button></div>
<p class="note">Tip: find a TMDB ID on themoviedb.org — open a movie or show there and copy the number from its URL. For anime, use the AniList ID, not the TMDB ID.</p>
</div></section>
<div id="onlinePlayer"><div class="playerTop"><b id="onlineTitle">Online player</b>
<button type="button" class="close" id="onlineExitBtn">✕ Exit</button></div>
<iframe id="onlineFrame" allow="autoplay; fullscreen; encrypted-media; picture-in-picture; presentation" allowfullscreen></iframe></div>
<div id="player"><div class="playerTop"><b id="pTitle"></b>
<button type="button" class="close" id="closePlayerBtn">✕ Back</button></div>
<video id="video" controls autoplay playsinline preload="metadata"></video>
<div class="tvbar"><button type="button" id="btnPlayPause">⏯ Play / Pause</button>
<button type="button" id="btnBack10">⏪ -10s</button>
<button type="button" id="btnFwd10">+10s ⏩</button>
<button type="button" id="btnPlayerBack">✕ Back</button></div></div>
<div id="seriesModal"><div class="modalTop"><b id="sTitle"></b>
<button type="button" class="close" id="closeSeriesBtn">✕ Back</button></div><div class="epList" id="epList"></div></div>
<div id="offlineOverlay"><div class="offlineBox"><div class="logo" style="margin-bottom:12px">CASTFLIX</div>
<h2 style="margin-top:0">Server offline</h2>
<p class="note" style="color:#ddd;font-size:16px">Your phone server is not reachable. Your local files need the phone, but you can continue online instead.</p>
<p class="note" id="offlineCountdown"></p>
<div class="heroBtns" style="justify-content:center"><button type="button" class="btnPlay" id="offlineGoBtn">Open CineLite</button>
<button type="button" class="btnInfo" id="offlineRetryBtn">Try Again</button>
<button type="button" class="btnInfo" id="offlineStayBtn">Stay Here</button></div>
</div></div>
<div id="lock"><div class="lockBox"><div class="logo" style="margin-bottom:14px">CASTFLIX</div><h2 style="margin-top:0">Enter PIN</h2>
<input id="pin" type="password" inputmode="numeric" placeholder="PIN">
<div><button type="button" id="unlockBtn">Unlock</button></div><p class="note" id="pinErr"></p></div></div>
<script>
let LIB=null, TAB='all', CUR=null, CUR_SERIES=null, LAST_CARD_ID=null, HERO=null;
const params=new URLSearchParams(location.search);
let TV_MODE=params.get('tv')==='1'||localStorage.getItem('castflix_tv')==='1';
if(params.get('tv')==='1') localStorage.setItem('castflix_tv','1');
if(TV_MODE) document.body.classList.add('tv');
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const prog=id=>{const v=localStorage.getItem('castflix_'+id);return v?parseFloat(v):0};
function hue(t){let h=0;for(const c of t)h=(h*31+c.charCodeAt(0))%360;return h}
function cardHTML(item,isSeries,progress){
 const p=(progress!==undefined)?progress:(isSeries?Math.max(0,...item.episodes.map(e=>prog(e.id))):prog(item.id));
 return `<button type="button" class="card focusable" data-id="${item.id}" data-series="${isSeries?1:0}">
  <div class="poster" style="background:linear-gradient(135deg,hsl(${hue(item.title)} 80% 45%),#111)">
   ${item.poster_url?`<img src="${item.poster_url}" alt="" loading="lazy">`:`<div class="titleOverlay">${esc(item.title)}</div>`}
   <div class="playIcon">▶</div>
  </div><div class="meta"><b>${esc(item.title)}</b>
  <small>${item.year||''} ${isSeries?('· '+item.episodes.length+' episodes'):''}</small>
  <div>${!isSeries?`<span class="ext">${esc((item.ext||'').replace('.','').toUpperCase())}</span>`:''}
  ${!isSeries && !item.browser_friendly?'<span class="badge">May not play in TV browser</span>':''}</div>
  ${p>0.02&&p<0.95?`<div class="progress"><i style="width:${Math.min(100,p*100)}%"></i></div>`:''}
  </div></button>`;
}
function renderHero(movies,series,cont){
 if(typeof ONLINE_MODE!=='undefined' && ONLINE_MODE){ $('hero').style.display='none'; return; }
 const pick=cont.length?cont[0]: (movies.length?[movies[0],false,0]: (series.length?[series[0],true,0]:null));
 if(!pick){$('hero').style.display='none';HERO=null;return;}
 const [item,isSeries]=pick; HERO=[item,isSeries];
 $('hero').style.display='flex';
 $('heroEyebrow').textContent=cont.length?'Continue Watching':'Featured';
 $('heroTitle').textContent=item.title;
 $('heroMeta').textContent=[item.year||'',isSeries?(item.episodes.length+' episodes'):(item.ext||'').toUpperCase(),'Direct play · Original quality'].filter(Boolean).join('  ·  ');
 $('heroBg').innerHTML=item.poster_url?`<img src="${item.poster_url}" alt="">`:'';
 $('heroBg').style.background=item.poster_url?'':`linear-gradient(135deg,hsl(${hue(item.title)} 80% 45%),#111)`;
 $('heroInfoBtn').style.display=isSeries?'block':'none';
}
function render(){
 if(!LIB) return;
 const q=($('q').value||'').toLowerCase();
 const showMovies=TAB==='all'||TAB==='movies';
 const showSeries=TAB==='all'||TAB==='series';
 $('hMovies').style.display=showMovies?'block':'none';
 $('movies').style.display=showMovies?'flex':'none';
 $('hSeries').style.display=showSeries?'block':'none';
 $('series').style.display=showSeries?'flex':'none';
 const movies=LIB.movies.filter(m=>m.title.toLowerCase().includes(q));
 const series=LIB.series.filter(s=>s.title.toLowerCase().includes(q));
 const cont=[];
 for(const m of movies){const p=prog(m.id); if(p>0.02&&p<0.95) cont.push([m,false,p]);}
 for(const s of series){const p=Math.max(0,...s.episodes.map(e=>prog(e.id))); if(p>0.02&&p<0.95) cont.push([s,true,p]);}
 $('hContinue').style.display=cont.length?'block':'none';
 $('continue').style.display=cont.length?'flex':'none';
 $('continue').innerHTML=cont.map(([it,isS,p])=>cardHTML(it,isS,p)).join('');
 $('movies').innerHTML=movies.length?movies.map(m=>cardHTML(m,false)).join(''):'<p class="note">No movies found.</p>';
 $('series').innerHTML=series.length?series.map(s=>cardHTML(s,true)).join(''):'<p class="note">No series found.</p>';
 $('status').textContent=`${LIB.movies.length} movies · ${LIB.series.length} series on this phone`;
 renderHero(movies,series,cont);
 if(TV_MODE && !document.querySelector('.card:focus')){
   const first=document.querySelector('.card'); if(first) first.focus();
 }
}
async function load(){
 try{
  const st=await fetch('/api/status').then(r=>r.json());
  if(st.pin_required){
   const r=await fetch('/api/library');
   if(r.status===401){$('lock').classList.add('show');$('pin').focus();return;}
  }
  LIB=await fetch('/api/library').then(r=>{if(!r.ok) throw new Error(r.status); return r.json();});
  render();
 }catch(e){ $('status').textContent='Could not load library. Is the phone server still running on the same Wi-Fi? Reload the page to retry.'; }
}
async function unlock(){
 const pin=$('pin').value;
 const r=await fetch('/api/unlock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin})});
 if(r.ok){$('lock').classList.remove('show');load();}
 else $('pinErr').textContent='Wrong PIN';
}
function find(id){
 for(const m of LIB.movies) if(m.id===id) return [m,false];
 for(const s of LIB.series) if(s.id===id) return [s,true];
 return [null,false];
}
function openItem(id,isSeries){
 const [item]=find(id); if(!item) return;
 LAST_CARD_ID=id;
 if(isSeries){
   CUR_SERIES=item;
   $('sTitle').textContent=item.title;
   $('epList').innerHTML=item.episodes.map(e=>
    `<button type="button" class="epBtn focusable" data-ep-id="${e.id}"><span><b>${esc(e.title)}</b>${e.browser_friendly?'':' · may not play in browser'}</span><span>▶</span></button>`).join('');
   $('seriesModal').classList.add('show');
   const first=$('epList').querySelector('button'); if(first) first.focus();
   return;
 }
 play(item,item.title);
}
function play(item,title){
 CUR=item; $('pTitle').textContent=title;
 const v=$('video');
 v.pause(); v.innerHTML='';
 const src=document.createElement('source'); src.src='/stream?id='+item.id; v.appendChild(src);
 if(item.has_subtitles){
   const tr=document.createElement('track'); tr.kind='subtitles'; tr.src='/subtitles?id='+item.id; tr.default=true; v.appendChild(tr);
 }
 $('player').classList.add('show');
 v.load();
 v.onloadedmetadata=()=>{const p=prog(item.id); if(p>0.02&&p<0.95&&v.duration) v.currentTime=p*v.duration;};
 v.onended=()=>{
   localStorage.setItem('castflix_'+item.id,'1');
   if(CUR_SERIES){
     const idx=CUR_SERIES.episodes.findIndex(e=>e.id===item.id);
     const nxt=CUR_SERIES.episodes[idx+1];
     if(nxt){ play(nxt, CUR_SERIES.title+' '+nxt.title); return; }
   }
   closePlayer();
 };
 let last=0; v.ontimeupdate=()=>{if(v.duration&&Date.now()-last>4000){last=Date.now();
   localStorage.setItem('castflix_'+item.id,(v.currentTime/v.duration).toFixed(3));}};
 v.play().catch(()=>{});
}
function closePlayer(){
 const v=$('video'); v.pause(); v.innerHTML=''; v.load();
 $('player').classList.remove('show');
 const y=window.scrollY; render(); window.scrollTo(0,y);
 if(LAST_CARD_ID){const el=document.querySelector(`.card[data-id="${LAST_CARD_ID}"]`); if(el) el.focus();}
}
function closeSeries(){ $('seriesModal').classList.remove('show'); }
function togglePlay(){const v=$('video'); if(v.paused) v.play().catch(()=>{}); else v.pause();}
function seekBy(sec){const v=$('video'); if(v.duration) v.currentTime=Math.max(0,Math.min(v.duration,v.currentTime+sec));}
function moveFocus(dx,dy){
 const els=[...document.querySelectorAll('input, select, .tabs button, .tvBtn, .heroBtn, .card, .epBtn, .tvbar button, .onlineBtn, .presetBtn')].filter(e=>e.offsetParent!==null);
 if(!els.length) return;
 const cur=document.activeElement;
 if(!els.includes(cur)){els[0].focus();return;}
 const r=cur.getBoundingClientRect(), cx=r.left+r.width/2, cy=r.top+r.height/2;
 let best=null,bestScore=Infinity;
 for(const el of els){
   if(el===cur) continue;
   const b=el.getBoundingClientRect(), ex=b.left+b.width/2, ey=b.top+b.height/2;
   const ddx=ex-cx, ddy=ey-cy;
   if(dx!==0 && Math.sign(ddx)!==dx) continue;
   if(dy!==0 && Math.sign(ddy)!==dy) continue;
   if(dx!==0 && Math.abs(ddy)>140) continue;
   if(dy!==0 && Math.abs(ddx)>240) continue;
   const score=Math.abs(ddx)+Math.abs(ddy)*2;
   if(score<bestScore){bestScore=score;best=el;}
 }
 if(best) best.focus();
}
document.addEventListener('focusin',e=>{
 if(e.target.classList && e.target.classList.contains('card')) e.target.scrollIntoView({block:'nearest',inline:'center'});
});
document.addEventListener('click',e=>{
 const card=e.target.closest('.card');
 if(card){openItem(card.dataset.id,card.dataset.series==='1');return;}
 const ep=e.target.closest('.epBtn');
 if(ep && CUR_SERIES){
   const item=CUR_SERIES.episodes.find(x=>x.id===ep.dataset.epId);
   if(item) play(item,CUR_SERIES.title+' '+item.title);
 }
});
$('q').addEventListener('input',render);
document.querySelectorAll('.tabs button').forEach(b=>b.addEventListener('click',()=>{
 showLocal();
 document.querySelectorAll('.tabs button').forEach(x=>x.classList.remove('active'));
 b.classList.add('active');TAB=b.dataset.tab;render();}));
$('tvBtn').addEventListener('click',()=>{
 if(TV_MODE){localStorage.removeItem('castflix_tv');location.search='';}
 else{localStorage.setItem('castflix_tv','1');location.search='?tv=1';}
});
if(TV_MODE){$('tvBtn').classList.add('on');$('tvBtn').textContent='TV mode: ON';}
$('heroPlayBtn').addEventListener('click',()=>{
 if(!HERO) return; const [item,isSeries]=HERO;
 if(isSeries) play(item.episodes[0], item.title+' '+item.episodes[0].title);
 else play(item,item.title);
});
$('heroInfoBtn').addEventListener('click',()=>{
 if(!HERO) return; const [item,isSeries]=HERO; if(isSeries) openItem(item.id,true);
});
$('closePlayerBtn').addEventListener('click',closePlayer);
$('btnPlayerBack').addEventListener('click',closePlayer);
$('closeSeriesBtn').addEventListener('click',closeSeries);
$('unlockBtn').addEventListener('click',unlock);
$('btnPlayPause').addEventListener('click',togglePlay);
$('btnBack10').addEventListener('click',()=>seekBy(-10));
$('btnFwd10').addEventListener('click',()=>seekBy(10));
$('pin').addEventListener('keydown',e=>{if(e.key==='Enter') unlock();});
document.addEventListener('keydown',e=>{
 if($('offlineOverlay').classList.contains('show')) return;
 if($('lock').classList.contains('show')) return;
 const inInput=document.activeElement && document.activeElement.tagName==='INPUT';
 if($('onlinePlayer').classList.contains('show')){
   if(e.key==='Escape'||e.key==='Backspace'){e.preventDefault();closeOnline();}
   return;
 }
 if($('player').classList.contains('show')){
   if(e.key==='ArrowLeft'){e.preventDefault();seekBy(-10);}
   else if(e.key==='ArrowRight'){e.preventDefault();seekBy(10);}
   else if(e.key==='Enter'||e.key===' '){
     if(document.activeElement && document.activeElement.tagName!=='BUTTON'){e.preventDefault();togglePlay();}
   }
   else if(e.key==='Escape'||e.key==='Backspace'){e.preventDefault();closePlayer();}
   return;
 }
 if($('seriesModal').classList.contains('show')){
   if(e.key==='Escape'||e.key==='Backspace'){e.preventDefault();closeSeries();return;}
   if(e.key==='ArrowDown'){e.preventDefault();moveFocus(0,1);}
   if(e.key==='ArrowUp'){e.preventDefault();moveFocus(0,-1);}
   return;
 }
 if(inInput) return;
 if(e.key==='ArrowRight'){e.preventDefault();moveFocus(1,0);}
 else if(e.key==='ArrowLeft'){e.preventDefault();moveFocus(-1,0);}
 else if(e.key==='ArrowDown'){e.preventDefault();moveFocus(0,1);}
 else if(e.key==='ArrowUp'){e.preventDefault();moveFocus(0,-1);}
});
/* ---- Online / CineLite tab ---- */
let ONLINE_MODE=false, ONLINE_COLOR='e50914';
function showLocal(){
 ONLINE_MODE=false; document.body.classList.remove('online');
 $('onlineBtn').classList.remove('on'); $('onlineBtn').textContent='🌐 Online';
 $('onlineSection').classList.remove('show'); $('hero').style.display=LIB?'flex':'none'; $('mainLocal').style.display='block';
 document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('active',x.dataset.tab===TAB));
}
function showOnline(){
 ONLINE_MODE=true; document.body.classList.add('online');
 $('onlineBtn').classList.add('on'); $('onlineBtn').textContent='🌐 Online: ON';
 document.querySelectorAll('.tabs button').forEach(x=>x.classList.remove('active'));
 $('hero').style.display='none'; $('mainLocal').style.display='none'; $('onlineSection').classList.add('show');
 const f=$('onId'); if(f) f.focus(); renderOnlineRecent();
}
function onlineTypeChanged(){
 const t=$('onType').value;
 $('onIdLabel').textContent=t==='anime'?'AniList ID':'TMDB ID';
 $('onSeasonField').style.display=t==='tv'?'block':'none';
 $('onEpisodeField').style.display=t==='tv'||t==='anime'?'block':'none';
}
function parseStartTime(s){
 s=(s||'').trim(); if(!s) return 0;
 if(/^\d+$/.test(s)) return parseInt(s,10);
 const hm=s.match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/);
 if(hm && (hm[1]||hm[2]||hm[3])) return (parseInt(hm[1]||0)*3600)+(parseInt(hm[2]||0)*60)+parseInt(hm[3]||0);
 const parts=s.split(':').map(Number);
 if(parts.some(isNaN)) return 0;
 if(parts.length===2) return parts[0]*60+parts[1];
 if(parts.length===3) return parts[0]*3600+parts[1]*60+parts[2];
 return 0;
}
function onlineKey(type,id,season,episode){
 return 'castflix_online_'+[type,id,season||'',episode||''].join('_');
}
function buildOnlineUrl(){
 const type=$('onType').value, id=$('onId').value.trim();
 $('onlineErr').textContent='';
 if(!id || !/^\d+$/.test(id)){ $('onlineErr').textContent='Enter a numeric ID first. For movies/TV use the TMDB ID, for anime use the AniList ID.'; return null; }
 let path='';
 if(type==='movie') path='/'+id;
 else if(type==='tv') path='/'+id+'/'+($('onSeason').value||'1')+'/'+($('onEpisode').value||'1');
 else path='/anime/'+id+'/'+($('onEpisode').value||'1');
 const q=new URLSearchParams();
 const color=($('onColor').value||'').replace('#','').trim();
 if(color) q.set('color',color);
 const qual=$('onQuality').value; if(qual) q.set('quality',qual);
 if($('onSuggest').checked) q.set('suggestionui','true');
 const reset=$('onReset').checked;
 let start=parseStartTime($('onStart').value);
 if(!reset && !start){
   const saved=localStorage.getItem(onlineKey(type,id,$('onSeason').value,$('onEpisode').value));
   if(saved){ try{ const o=JSON.parse(saved); if(o.currentTime>30) start=Math.floor(o.currentTime); }catch(e){} }
 }
 if(reset) q.set('reset','1'); else if(start>0) q.set('t',String(start));
 const qs=q.toString();
 return {url:'https://embed.cinelite.xyz'+path+(qs?'?'+qs:''), title: type==='movie'?'Online movie '+id : type==='tv'?'Online '+id+' S'+($('onSeason').value||'1')+'E'+($('onEpisode').value||'1') : 'Online anime '+id+' Ep '+($('onEpisode').value||'1')};
}
function renderOnlineRecent(){
 try{
   const list=JSON.parse(localStorage.getItem('castflix_online_recent')||'[]');
   $('onlineRecent').innerHTML=list.length?list.map(r=>`<button type="button" class="onlineBtn" data-online-url="${esc(r.url)}">${esc(r.title)}</button>`).join(''):'<span class="note">Nothing played online yet on this browser.</span>';
 }catch(e){}
}
function saveOnlineRecent(title,url){
 try{
   let list=JSON.parse(localStorage.getItem('castflix_online_recent')||'[]');
   list=[{title,url},...list.filter(r=>r.url!==url)].slice(0,8);
   localStorage.setItem('castflix_online_recent',JSON.stringify(list));
 }catch(e){}
 renderOnlineRecent();
}
function openOnlineUrl(url,title){
 $('onlineTitle').textContent=title||'Online player';
 $('onlineFrame').src=url; $('onlinePlayer').classList.add('show');
 if(title) saveOnlineRecent(title,url);
 const ex=$('onlineExitBtn'); if(ex) ex.focus();
}
function openOnline(){
 const built=buildOnlineUrl(); if(!built) return;
 $('onlineUrl').textContent=built.url;
 openOnlineUrl(built.url,built.title);
}
function closeOnline(){ $('onlineFrame').src=''; $('onlinePlayer').classList.remove('show'); }
$('onlineBtn').addEventListener('click',()=>{ ONLINE_MODE?showLocal():showOnline(); });
$('onType').addEventListener('change',onlineTypeChanged);
document.querySelectorAll('.presetBtn').forEach(b=>b.addEventListener('click',()=>{
 document.querySelectorAll('.presetBtn').forEach(x=>x.classList.remove('on'));
 b.classList.add('on'); ONLINE_COLOR=b.dataset.color; $('onColor').value=ONLINE_COLOR;
}));
$('onColor').addEventListener('input',e=>{ ONLINE_COLOR=e.target.value.replace('#',''); });
document.querySelectorAll('.featBtn').forEach(b=>b.addEventListener('click',()=>{
 $('onType').value=b.dataset.type; onlineTypeChanged();
 $('onId').value=b.dataset.id;
 if(b.dataset.season) $('onSeason').value=b.dataset.season;
 if(b.dataset.episode) $('onEpisode').value=b.dataset.episode;
 $('onStart').value=''; $('onReset').checked=false;
 showOnline(); const _b=buildOnlineUrl(); if(_b) openOnlineUrl(_b.url,b.dataset.title);
}));
$('onlinePlayBtn').addEventListener('click',openOnline);
$('onlineCopyBtn').addEventListener('click',()=>{
 const built=buildOnlineUrl(); if(!built) return;
 $('onlineUrl').textContent=built.url;
 if(navigator.clipboard) navigator.clipboard.writeText(built.url).then(()=>{$('onlineErr').textContent='Link copied.';}).catch(()=>{});
});
$('onlineExitBtn').addEventListener('click',closeOnline);
document.addEventListener('click',e=>{
 const r=e.target.closest('#onlineRecent button');
 if(r && r.dataset.onlineUrl) openOnlineUrl(r.dataset.onlineUrl,r.textContent);
});
window.addEventListener('message',e=>{
 if(!e.origin || !e.origin.includes('embed.cinelite.xyz')) return;
 const d=e.data||{};
 if(d.type==='CINELITE_EXIT_PLAYER'){ closeOnline(); return; }
 if(d.type && d.type.includes('PROGRESS')){
   try{
     const key=onlineKey(d.isAnime?'anime':(d.isTv?'tv':'movie'), d.mediaId||'', d.season||'', d.episode||'');
     localStorage.setItem(key, JSON.stringify({currentTime:d.currentTime||0,duration:d.duration||0,progress:d.progress||0,updatedAt:d.updatedAt||Date.now()}));
   }catch(err){}
 }
});
/* ---- Search by name (TMDB, runs from the TV browser) ---- */
function tmdbKeyGet(){ return localStorage.getItem('castflix_tmdb_key')||''; }
function tmdbKeySave(){
 const k=$('tmdbKey').value.trim();
 if(k) localStorage.setItem('castflix_tmdb_key',k); else localStorage.removeItem('castflix_tmdb_key');
 $('tmdbKeyStatus').textContent=k?'API key saved on this TV browser.':'API key cleared.';
}
async function searchByName(){
 const q=$('onSearchName').value.trim(); const key=tmdbKeyGet();
 if(!key){ $('onSearchErr').textContent='Add your free TMDB API key first. Create a free account on themoviedb.org, go to Settings > API, copy the API Key (v3), paste it above and tap Save.'; $('tmdbKey').focus(); return; }
 if(!q){ $('onSearchErr').textContent='Type a movie or show name first.'; return; }
 $('onSearchErr').textContent='Searching...'; $('onSearchResults').innerHTML='';
 try{
  const r=await fetch('https://api.themoviedb.org/3/search/multi?api_key='+encodeURIComponent(key)+'&query='+encodeURIComponent(q)+'&include_adult=false&page=1');
  if(!r.ok) throw new Error('TMDB returned '+r.status+' — check your API key.');
  const data=await r.json();
  const items=(data.results||[]).filter(x=>x.media_type==='movie'||x.media_type==='tv').slice(0,12);
  if(!items.length){ $('onSearchErr').textContent='No results for that name. Try a different spelling.'; return; }
  $('onSearchErr').textContent='';
  $('onSearchResults').innerHTML=items.map(x=>{
    const title=x.title||x.name||'Unknown'; const year=(x.release_date||x.first_air_date||'').slice(0,4);
    const poster=x.poster_path?('https://image.tmdb.org/t/p/w200'+x.poster_path):'';
    return `<button type="button" class="searchCard onlineBtn" data-search-type="${x.media_type}" data-search-id="${x.id}">
      ${poster?`<img src="${poster}" alt="" loading="lazy">`:`<div class="searchNoPoster">${esc(title)}</div>`}
      <span><b>${esc(title)}</b><small>${year} · ${x.media_type==='tv'?'TV':'Movie'} · ★ ${(x.vote_average||0).toFixed(1)}</small></span></button>`;
  }).join('');
 }catch(e){ $('onSearchErr').textContent='Search failed: '+e.message+' Check the TV internet connection and API key.'; }
}
$('tmdbSaveBtn').addEventListener('click',tmdbKeySave);
$('onSearchBtn').addEventListener('click',searchByName);
$('onSearchName').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();searchByName();}});
if($('tmdbKey')) $('tmdbKey').value=tmdbKeyGet();
document.addEventListener('click',e=>{
 const sc=e.target.closest('.searchCard');
 if(sc){
   $('onType').value=sc.dataset.searchType==='tv'?'tv':'movie'; onlineTypeChanged();
   $('onId').value=sc.dataset.searchId;
   if(sc.dataset.searchType==='tv'){ $('onSeason').value='1'; $('onEpisode').value='1'; }
   $('onStart').value=''; $('onReset').checked=false;
   openOnline();
 }
});
/* ---- Offline fallback: redirect to cinelite.xyz ---- */
let OFFLINE_FAILS=0, OFFLINE_COUNTDOWN_TIMER=null, OFFLINE_STAY_UNTIL=0;
function offlineRedirectEnabled(){ return localStorage.getItem('castflix_offline_redirect')==='1'; }
function stopOfflineCountdown(){ if(OFFLINE_COUNTDOWN_TIMER){clearInterval(OFFLINE_COUNTDOWN_TIMER);OFFLINE_COUNTDOWN_TIMER=null;} }
function showOffline(){
 if($('offlineOverlay').classList.contains('show')) return;
 $('offlineOverlay').classList.add('show');
 if(offlineRedirectEnabled()){
   let left=10; $('offlineCountdown').textContent='Redirecting to CineLite in '+left+' seconds — tap Stay Here to cancel.';
   stopOfflineCountdown();
   OFFLINE_COUNTDOWN_TIMER=setInterval(()=>{ left--; if(left<=0){ stopOfflineCountdown(); window.location.href='https://cinelite.xyz/'; } else $('offlineCountdown').textContent='Redirecting to CineLite in '+left+' seconds — tap Stay Here to cancel.'; },1000);
   const go=$('offlineGoBtn'); if(go) go.focus();
 } else {
   $('offlineCountdown').textContent='Auto-redirect is off. Tap Open CineLite to continue online, or Try Again if the phone is back.';
 }
}
function hideOffline(){ stopOfflineCountdown(); $('offlineOverlay').classList.remove('show'); }
async function checkServer(){
 if(Date.now()<OFFLINE_STAY_UNTIL) return;
 if($('onlinePlayer').classList.contains('show')) return;
 if($('lock').classList.contains('show')) return;
 try{
   const r=await fetch('/api/status',{cache:'no-store'});
   if(!r.ok) throw new Error('status '+r.status);
   OFFLINE_FAILS=0;
   if($('offlineOverlay').classList.contains('show')) hideOffline();
 }catch(e){
   OFFLINE_FAILS++;
   if(OFFLINE_FAILS>=2) showOffline();
 }
}
$('offlineGoBtn').addEventListener('click',()=>{ window.location.href='https://cinelite.xyz/'; });
$('goCineliteBtn').addEventListener('click',()=>{ window.location.href='https://cinelite.xyz/'; });
$('offlineRetryBtn').addEventListener('click',()=>{ hideOffline(); OFFLINE_FAILS=0; checkServer(); });
$('offlineStayBtn').addEventListener('click',()=>{ hideOffline(); OFFLINE_STAY_UNTIL=Date.now()+5*60*1000; });
$('offlineRedirectToggle').addEventListener('change',e=>{
 if(e.target.checked) localStorage.setItem('castflix_offline_redirect','1'); else localStorage.removeItem('castflix_offline_redirect');
});
if($('offlineRedirectToggle')) $('offlineRedirectToggle').checked=offlineRedirectEnabled();
onlineTypeChanged(); renderOnlineRecent();
load();
setInterval(checkServer,10000);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "CastFlix/0.7"

    # Filled in by main()
    library = {}
    by_id = {}
    pin = None

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _pin_ok(self):
        if not self.pin:
            return True
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("castflix_pin="):
                return part.split("=", 1)[1] == self.pin
        return False

    def _send_json(self, obj, status=200, extra=None):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _serve_file_range(self, path, content_type):
        size = os.path.getsize(path)
        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))
                end = min(end, size - 1)
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)

        if path == "/":
            data = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/api/status":
            self._send_json({"pin_required": bool(self.pin)})
            return

        if not self._pin_ok():
            self._send_json({"error": "PIN required"}, status=401)
            return

        if path == "/api/library":
            self._send_json(self.library)
            return

        item_id = query.get("id", [None])[0]
        item = self.by_id.get(item_id) if item_id else None
        if path == "/stream" and item and "path" in item:
            ctype, _ = mimetypes.guess_type(item["path"])
            self._serve_file_range(item["path"], ctype or "video/mp4")
            return
        if path == "/poster" and item and "poster" in item:
            ctype, _ = mimetypes.guess_type(item["poster"])
            self._serve_file_range(item["poster"], ctype or "image/jpeg")
            return
        if path == "/subtitles" and item and "subs" in item:
            subs = item["subs"]
            if "vtt" in subs:
                self._serve_file_range(subs["vtt"], "text/vtt")
                return
            if "srt" in subs:
                data = srt_to_vtt(subs["srt"]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/vtt")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        self.send_response(404)
        self.end_headers()

    do_HEAD = do_GET

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/unlock":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            if self.pin and body.get("pin") == self.pin:
                self._send_json({"ok": True}, extra={
                    "Set-Cookie": "castflix_pin=" + self.pin + "; Path=/; Max-Age=86400"})
            else:
                self._send_json({"error": "wrong PIN"}, status=401)
            return
        self.send_response(404)
        self.end_headers()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--media", default="./media")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--pin", default=None, help="Optional 4-digit PIN for the TV browser")
    args = ap.parse_args()

    root = os.path.abspath(args.media)
    if not os.path.isdir(root):
        print(f"Media folder not found: {root}", file=sys.stderr)
        print("Create it, or pass --media /path/to/your/movies", file=sys.stderr)
        return 2

    library, by_id = scan_library(root)
    Handler.library = library
    Handler.by_id = by_id
    Handler.pin = args.pin

    ip = lan_ip()
    print("CastFlix prototype", flush=True)
    print(f"Found: {len(library['movies'])} movies, {len(library['series'])} series in {root}", flush=True)
    print(f"On this device: http://127.0.0.1:{args.port}", flush=True)
    print(f"On your TV browser (same Wi-Fi): http://{ip}:{args.port}", flush=True)
    if args.pin:
        print("PIN protection is ON.", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

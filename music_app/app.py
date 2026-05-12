"""
app.py — Music Recommender Web App
Flask backend que usa el mismo sistema Last.fm + YouTube

Instalar:
    pip install flask yt-dlp requests

Correr:
    python app.py
Abrir:
    http://localhost:5000
"""

from flask import Flask, render_template, request, jsonify
import re, json, time, math, hashlib, random
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import defaultdict

import requests as req

try:
    import yt_dlp
except ImportError:
    raise SystemExit("Instala yt-dlp: pip install yt-dlp")

app = Flask(__name__)

# ══════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════

LASTFM_API_KEY = "b32b1442f91e8c08574f62329f91c899"
LASTFM_URL     = "https://ws.audioscrobbler.com/2.0/"


# ══════════════════════════════════════════════════════════════════
# URL RESOLVER
# ══════════════════════════════════════════════════════════════════

YT_URL = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})"
)

class URLResolver:
    def resolve(self, raw: str, artist_hint: str) -> tuple[str, str]:
        if not YT_URL.search(raw):
            return raw, artist_hint
        # noembed.com — gratis, sin key, funciona en cualquier servidor
        try:
            resp = req.get(
                f"https://noembed.com/embed?url={raw}",
                timeout=8
            )
            data = resp.json()
            title  = data.get("title") or raw
            artist = self._artist_from_title(title) or artist_hint
            return title, artist
        except Exception:
            return raw, artist_hint

    def _artist_from_title(self, title: str) -> str:
        clean = re.sub(
            r"\s*[\(\[]?(official\s*(music\s*)?video|lyric\s*video|audio|hd|hq|mv|lyrics)[\)\]]?",
            "", title, flags=re.IGNORECASE
        ).strip()
        for sep in [" - ", " \u2013 ", " : ", " | "]:
            if sep in clean:
                candidate = clean.split(sep)[0].strip()
                if 1 < len(candidate) <= 40:
                    return candidate
        return ""


# ══════════════════════════════════════════════════════════════════
# LAST.FM CLIENT
# ══════════════════════════════════════════════════════════════════

@dataclass
class SimilarArtist:
    name: str
    match: float

@dataclass
class VideoResult:
    title:         str
    url:           str
    duration:      int
    view_count:    int
    channel:       str
    target_artist: str
    score:         float = 0.0

    def duration_fmt(self) -> str:
        m, s = divmod(self.duration, 60)
        return f"{m}:{s:02d}"


class LastFMClient:
    def get_similar_artists(self, artist: str, limit: int = 10) -> list[SimilarArtist]:
        params = {
            "method":  "artist.getSimilar",
            "artist":  artist,
            "api_key": LASTFM_API_KEY,
            "format":  "json",
            "limit":   limit,
        }
        try:
            resp = req.get(LASTFM_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                return []
            artists = data.get("similarartists", {}).get("artist", [])
            return [SimilarArtist(name=a["name"], match=float(a.get("match", 0)))
                    for a in artists if a.get("name")]
        except Exception:
            return []

    def get_top_tracks(self, artist: str, limit: int = 3) -> list[str]:
        params = {
            "method":  "artist.getTopTracks",
            "artist":  artist,
            "api_key": LASTFM_API_KEY,
            "format":  "json",
            "limit":   limit,
        }
        try:
            resp = req.get(LASTFM_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            tracks = data.get("toptracks", {}).get("track", [])
            return [t["name"] for t in tracks if t.get("name")]
        except Exception:
            return []


# ══════════════════════════════════════════════════════════════════
# QUERY GENERATOR
# ══════════════════════════════════════════════════════════════════

class SmartQueryGenerator:
    def __init__(self):
        self.lastfm = LastFMClient()

    def generate(self, title: str, artist: str) -> list[tuple[str, str]]:
        # Pide 12 artistas similares para tener variedad
        similar = self.lastfm.get_similar_artists(artist, limit=12)
        if not similar:
            return self._fallback(title, artist)

        # Mezcla aleatoriamente los 12 artistas
        # Pero da más peso a los más similares — toma 4 del top 6 y 2 del resto
        top6    = similar[:6]
        rest    = similar[6:]
        random.shuffle(top6)
        random.shuffle(rest)
        chosen  = top6[:4] + rest[:2]
        random.shuffle(chosen)

        queries = []
        for sim in chosen:
            # Pide top 5 canciones y elige una al azar
            tracks = self.lastfm.get_top_tracks(sim.name, limit=5)
            if tracks:
                # Elige aleatoriamente entre las top 5
                track = random.choice(tracks)
                queries.append((f"{sim.name} {track} official", sim.name))
                # Segunda canción diferente si hay más
                remaining = [t for t in tracks if t != track]
                if remaining:
                    track2 = random.choice(remaining)
                    queries.append((f"{sim.name} {track2} official", sim.name))
            else:
                queries.append((f"{sim.name} official music video", sim.name))

        return queries[:10]

    def _fallback(self, title: str, artist: str) -> list[tuple[str, str]]:
        clean = re.sub(r"https?://\S+", "", f"{title} {artist}")
        clean = re.sub(r"[^\w\s]", " ", clean).strip()
        return [
            (f"songs similar to {clean}", artist),
            (f"{artist} similar bands playlist", artist),
        ]


# ══════════════════════════════════════════════════════════════════
# YOUTUBE FETCHER + CACHE
# ══════════════════════════════════════════════════════════════════

NOISE_WORDS = {
    "tutorial", "lesson", "theory", "teach", "learn", "explain",
    "interview", "reaction", "review", "podcast", "talk", "lecture",
    "trailer", "teaser", "promo", "advertisement",
    "piano cover", "acoustic cover", "karaoke", "drum cover",
    "how to", "gaming", "gameplay", "minecraft", "roblox",
    "undertale", "anime", "amv",
    "1 hour", "2 hours", "3 hours", "10 hours",
    "wedding", "funeral", "sleep music",
    "documentary", "biography", "story of",
}

class YouTubeFetcher:
    CACHE_FILE = Path(".yt_cache.json")
    CACHE_TTL  = 60 * 60 * 24

    def __init__(self, max_per_query: int = 5):
        self.max_per_query = max_per_query
        self._cache = self._load_cache()

    def _load_cache(self) -> dict:
        if self.CACHE_FILE.exists():
            try:
                data = json.loads(self.CACHE_FILE.read_text())
                now  = time.time()
                return {k: v for k, v in data.items()
                        if now - v.get("ts", 0) < self.CACHE_TTL}
            except Exception:
                pass
        return {}

    def _save_cache(self) -> None:
        try:
            self.CACHE_FILE.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def _key(self, q: str) -> str:
        return hashlib.md5(q.encode()).hexdigest()

    def fetch_many(self, queries: list[tuple[str, str]]) -> list[VideoResult]:
        results = []
        for query, target_artist in queries:
            results.extend(self._fetch_one(query, target_artist))
            time.sleep(0.3)
        return results

    def _fetch_one(self, query: str, target_artist: str,
                   retries: int = 3) -> list[VideoResult]:
        key = self._key(query)
        if key in self._cache:
            return [VideoResult(**{**v, "target_artist": target_artist})
                    for v in self._cache[key]["data"]]
        opts = {
            "quiet": True, "no_warnings": True,
            "extract_flat": True, "skip_download": True,
            "socket_timeout": 15,
        }
        for attempt in range(retries):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(
                        f"ytsearch{self.max_per_query}:{query}", download=False)
                videos = []
                for e in (info.get("entries") or []):
                    if not e:
                        continue
                    vid_id = e.get("id") or ""
                    url = (f"https://www.youtube.com/watch?v={vid_id}"
                           if vid_id else e.get("webpage_url") or "")
                    if not url:
                        continue
                    videos.append(VideoResult(
                        title         = e.get("title", ""),
                        url           = url,
                        duration      = int(e.get("duration") or 0),
                        view_count    = e.get("view_count") or 0,
                        channel       = e.get("channel") or e.get("uploader") or "",
                        target_artist = target_artist,
                    ))
                self._cache[key] = {"ts": time.time(),
                                    "data": [v.__dict__ for v in videos]}
                self._save_cache()
                return videos
            except Exception as err:
                time.sleep(2 ** attempt + random.uniform(0, 1))
        return []


# ══════════════════════════════════════════════════════════════════
# FILTER + SCORER
# ══════════════════════════════════════════════════════════════════

class FilterScorer:
    MIN_DUR        = 90
    MAX_DUR        = 600
    MAX_PER_ARTIST = 1

    def filter_and_score(self, videos: list[VideoResult],
                         original_artist: str) -> list[VideoResult]:
        seen_ids     = set()
        seen_titles  = set()
        artist_count = defaultdict(int)
        filtered     = []

        for v in videos:
            vid_id    = self._vid_id(v.url)
            title_key = self._norm_title(v.title)

            if v.duration < self.MIN_DUR or v.duration > self.MAX_DUR:
                continue
            if self._is_noise(v.title):
                continue
            if self._is_original(v.channel, original_artist):
                continue
            if vid_id in seen_ids or title_key in seen_titles:
                continue

            ch_key = self._norm(v.channel)
            if artist_count[ch_key] >= self.MAX_PER_ARTIST:
                continue

            seen_ids.add(vid_id)
            seen_titles.add(title_key)
            artist_count[ch_key] += 1
            v.score = self._score(v)
            filtered.append(v)

        return sorted(filtered, key=lambda x: x.score, reverse=True)

    def _is_noise(self, title: str) -> bool:
        t = title.lower()
        return any(n in t for n in NOISE_WORDS)

    def _is_original(self, channel: str, artist: str) -> bool:
        a  = artist.lower().strip()
        ch = self._norm(channel)
        return len(a) >= 3 and (ch == a or ch.startswith(a))

    def _norm(self, channel: str) -> str:
        return re.sub(
            r"\s*[-\u2013]\s*(topic|vevo|official|music|records|label).*",
            "", channel.lower()).strip()

    def _norm_title(self, title: str) -> str:
        t = title.lower()
        t = re.sub(r"\b(sub|subtitulado|subtitles?|espa\u00f1ol|english|lyrics?|"
                   r"hd|hq|official|video|audio|traduccion|traducci\u00f3n|"
                   r"letra|karaoke|nightcore|slowed|reverb)\b", "", t)
        return re.sub(r"[^\w]", "", t).strip()

    def _vid_id(self, url: str) -> str:
        m = re.search(r"v=([A-Za-z0-9_-]{11})", url)
        return m.group(1) if m else url

    def _score(self, v: VideoResult) -> float:
        score = 0.0
        t  = v.title.lower()
        ch = self._norm(v.channel)
        if v.target_artist.lower() in ch:
            score += 3.0
        if v.target_artist.lower() in t:
            score += 1.5
        if v.view_count > 0:
            score += min(math.log10(v.view_count) / 10, 0.5)
        if any(w in t for w in ["mix", "compilation", "top 10", "best of"]):
            score -= 1.5
        return round(score, 3)


# ══════════════════════════════════════════════════════════════════
# RECOMENDADOR
# ══════════════════════════════════════════════════════════════════

resolver  = URLResolver()
query_gen = SmartQueryGenerator()
fetcher   = YouTubeFetcher(max_per_query=5)
scorer    = FilterScorer()

def recommend(raw_input: str, artist: str, n: int = 5) -> dict:
    title, artist = resolver.resolve(raw_input, artist)
    queries = query_gen.generate(title, artist)
    raw     = fetcher.fetch_many(queries)
    ranked  = scorer.filter_and_score(raw, artist)
    top     = ranked[:n]

    return {
        "title":   title,
        "artist":  artist,
        "results": [
            {
                "title":         r.title,
                "url":           r.url,
                "duration":      r.duration_fmt(),
                "channel":       r.channel,
                "target_artist": r.target_artist,
                "score":         r.score,
            }
            for r in top
        ]
    }


# ══════════════════════════════════════════════════════════════════
# RUTAS FLASK
# ══════════════════════════════════════════════════════════════════

@app.route("/ads.txt")
def ads_txt():
    return "google.com, pub-7088507477090236, DIRECT, f08c47fec0942fa0", 200, {"Content-Type": "text/plain"}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/daily", methods=["POST"])
def daily():
    """Devuelve la canción más popular de un artista para la canción del día."""
    data   = request.get_json()
    artist = data.get("artist", "").strip()
    if not artist:
        return jsonify({"error": "Artista requerido"}), 400
    try:
        tracks = query_gen.lastfm.get_top_tracks(artist, limit=5)
        if not tracks:
            return jsonify({"error": "Sin resultados"}), 404
        track = random.choice(tracks)
        # Busca el video en YouTube
        results = fetcher._fetch_one(f"{artist} {track} official", artist)
        ranked  = scorer.filter_and_score(results, "")
        if ranked:
            r = ranked[0]
            return jsonify({"title": r.title, "url": r.url})
        return jsonify({"error": "Sin resultados"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/search", methods=["POST"])
def search():
    data      = request.get_json()
    raw_input = data.get("query", "").strip()
    artist    = data.get("artist", "").strip()
    if not raw_input:
        return jsonify({"error": "Ingresa una canción o URL"}), 400
    try:
        result = recommend(raw_input, artist)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("=" * 50)
    print("  Music Recommender — abriendo en http://localhost:5000")
    print("=" * 50)
    app.run(debug=False, port=5000)

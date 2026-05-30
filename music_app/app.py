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

import os
from flask import send_from_directory

# Detecta automáticamente si la carpeta es 'static' o 'estática'
_base = os.path.dirname(__file__)
_static = os.path.join(_base, 'static') if os.path.exists(os.path.join(_base, 'static')) else os.path.join(_base, 'estática')

app = Flask(__name__, static_folder=_static)

# ── Rate Limiting ─────────────────────────────────────────────────
RATE_LIMIT     = 20   # búsquedas por IP por hora
RATE_WINDOW    = 3600 # 1 hora en segundos

def check_rate_limit(ip: str) -> bool:
    """Retorna True si el IP puede hacer la búsqueda, False si excedió el límite."""
    if not REDIS_URL:
        return True  # Sin Redis no hay rate limit
    key = f"sonar:rate:{hashlib.md5(ip.encode()).hexdigest()}"
    try:
        val = redis_get(key)
        count = int(val) if val else 0
        if count >= RATE_LIMIT:
            return False
        # Incrementa contador
        new_count = count + 1
        redis_set(key, str(new_count), RATE_WINDOW)
        return True
    except Exception:
        return True  # Si falla Redis, permite la búsqueda

# ══════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════

LASTFM_API_KEY = "b32b1442f91e8c08574f62329f91c899"
LASTFM_URL     = "https://ws.audioscrobbler.com/2.0/"
GENIUS_TOKEN   = os.environ.get("GENIUS_API_TOKEN", "")
GENIUS_URL     = "https://api.genius.com"


# ══════════════════════════════════════════════════════════════════
# GENIUS CLIENT
# ══════════════════════════════════════════════════════════════════

class GeniusClient:
    """Busca canciones en Genius y obtiene métricas de engagement."""

    def search_song(self, title: str, artist: str) -> dict:
        """Busca una canción y retorna sus métricas."""
        if not GENIUS_TOKEN:
            return {}
        try:
            resp = req.get(
                f"{GENIUS_URL}/search",
                headers={"Authorization": f"Bearer {GENIUS_TOKEN}"},
                params={"q": f"{artist} {title}"},
                timeout=8
            )
            data = resp.json()
            hits = data.get("response", {}).get("hits", [])
            if not hits:
                return {}
            # Toma el primer resultado
            song = hits[0].get("result", {})
            return {
                "title":            song.get("title", ""),
                "artist":           song.get("primary_artist", {}).get("name", ""),
                "pageviews":        song.get("stats", {}).get("pageviews", 0),
                "annotations":      song.get("annotation_count", 0),
                "genius_url":       song.get("url", ""),
            }
        except Exception:
            return {}

    def get_hidden_gems(self, genre_artists: list[str], limit: int = 5) -> list[dict]:
        """
        Busca joyas ocultas — canciones con alto engagement en Genius
        pero artistas poco conocidos.
        """
        gems = []
        for artist in genre_artists[:8]:
            try:
                resp = req.get(
                    f"{GENIUS_URL}/search",
                    headers={"Authorization": f"Bearer {GENIUS_TOKEN}"},
                    params={"q": artist},
                    timeout=8
                )
                data = resp.json()
                hits = data.get("response", {}).get("hits", [])
                for hit in hits[:3]:
                    song = hit.get("result", {})
                    pageviews   = song.get("stats", {}).get("pageviews", 0)
                    annotations = song.get("annotation_count", 0)
                    # Joya = muchas anotaciones relativas a las vistas
                    # Alta obsesión de fans pero no mainstream
                    if annotations >= 3 and pageviews < 500_000:
                        gems.append({
                            "title":      song.get("title", ""),
                            "artist":     song.get("primary_artist", {}).get("name", ""),
                            "pageviews":  pageviews,
                            "annotations": annotations,
                            "score":      annotations / max(pageviews, 1) * 100_000,
                        })
            except Exception:
                continue

        # Ordena por score — más obsesión relativa primero
        gems.sort(key=lambda x: x["score"], reverse=True)
        return gems[:limit]


# ══════════════════════════════════════════════════════════════════
# URL RESOLVER
# ══════════════════════════════════════════════════════════════════

YT_URL = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})"
)

class MusicBrainz:
    """
    Detecta artista desde título de canción usando MusicBrainz.
    Gratis, sin API key, funciona en cualquier servidor.
    """
    BASE = "https://musicbrainz.org/ws/2"
    HEADERS = {"User-Agent": "SonarApp/1.0 (music recommender)"}

    def find_artist(self, title: str) -> str:
        """Dado un título de canción, devuelve el artista más probable."""
        # Limpia el título antes de buscar
        clean = re.sub(
            r"\s*[\(\[]?(official|lyrics?|video|hd|hq|audio|mv|live|remix)[\)\]]?",
            "", title, flags=re.IGNORECASE
        ).strip()
        # Quita el artista si ya viene en el título (formato "Artista - Canción")
        song = clean
        for sep in [" - ", " – ", " | ", " : "]:
            if sep in clean:
                parts = clean.split(sep)
                song = parts[1].strip() if len(parts) > 1 else clean
                break
        try:
            resp = req.get(
                f"{self.BASE}/recording",
                params={
                    "query": f'recording:"{song}"',
                    "limit": 3,
                    "fmt":   "json",
                },
                headers=self.HEADERS,
                timeout=8,
            )
            data = resp.json()
            recordings = data.get("recordings", [])
            if recordings:
                credits = recordings[0].get("artist-credit", [])
                if credits:
                    return credits[0].get("artist", {}).get("name", "")
        except Exception:
            pass
        return ""


class URLResolver:
    def __init__(self):
        self.mb = MusicBrainz()

    def resolve(self, raw: str, artist_hint: str) -> tuple[str, str]:
        if not YT_URL.search(raw):
            # No es URL — intenta detectar artista del texto con MusicBrainz
            if not artist_hint:
                artist_hint = self.mb.find_artist(raw) or artist_hint
            return raw, artist_hint

        # Es URL — usa noembed para obtener el título
        try:
            resp = req.get(
                f"https://noembed.com/embed?url={raw}",
                timeout=8
            )
            data = resp.json()
            title  = data.get("title") or raw
            artist = self._artist_from_title(title)

            # Si no detectamos artista del título, usamos MusicBrainz
            if not artist:
                artist = self.mb.find_artist(title)

            # Último fallback: hint del usuario
            artist = artist or artist_hint
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

    def get_similar_tracks(self, artist: str, track: str,
                           limit: int = 10) -> list[tuple[str, str]]:
        """
        Devuelve canciones similares a una canción específica.
        Retorna lista de (artista, titulo).
        """
        params = {
            "method":  "track.getSimilar",
            "artist":  artist,
            "track":   track,
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
            tracks = data.get("similartracks", {}).get("track", [])
            result = []
            for t in tracks:
                name   = t.get("name", "")
                artist_name = t.get("artist", {}).get("name", "")
                if name and artist_name:
                    result.append((artist_name, name))
            return result
        except Exception:
            return []

    def get_track_tags(self, artist: str, track: str) -> list[str]:
        """Obtiene tags de una canción específica — romantic, chill, dark, etc."""
        params = {
            "method":  "track.getInfo",
            "artist":  artist,
            "track":   track,
            "api_key": LASTFM_API_KEY,
            "format":  "json",
        }
        try:
            resp = req.get(LASTFM_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            tags = data.get("track", {}).get("toptags", {}).get("tag", [])
            return [t["name"].lower() for t in tags if t.get("name")]
        except Exception:
            return []


# ══════════════════════════════════════════════════════════════════
# QUERY GENERATOR
# ══════════════════════════════════════════════════════════════════

class SmartQueryGenerator:
    def __init__(self):
        self.lastfm = LastFMClient()

    def generate(self, title: str, artist: str) -> list[tuple[str, str]]:
        queries = []

        # Extrae título limpio de la canción (sin artista)
        song_title = self._extract_song_title(title, artist)

        # PASO 1: track.getSimilar — canciones similares a esta canción específica
        if song_title:
            similar_tracks = self.lastfm.get_similar_tracks(artist, song_title, limit=8)
            if similar_tracks:
                # Mezcla para variedad
                random.shuffle(similar_tracks)
                for sim_artist, sim_track in similar_tracks[:6]:
                    queries.append((f"{sim_artist} {sim_track} official", sim_artist))
                # Si hay suficientes resultados, retorna directo
                if len(queries) >= 5:
                    return queries[:10]

        # PASO 2: fallback a artist.getSimilar si track.getSimilar no dio resultados
        similar_artists = self.lastfm.get_similar_artists(artist, limit=12)
        if similar_artists:
            top6 = similar_artists[:6]
            rest = similar_artists[6:]
            random.shuffle(top6)
            random.shuffle(rest)
            chosen = top6[:4] + rest[:2]
            random.shuffle(chosen)

            for sim in chosen:
                tracks = self.lastfm.get_top_tracks(sim.name, limit=5)
                if tracks:
                    track = random.choice(tracks)
                    queries.append((f"{sim.name} {track} official", sim.name))
                    remaining = [t for t in tracks if t != track]
                    if remaining:
                        queries.append((f"{sim.name} {random.choice(remaining)} official", sim.name))
                else:
                    queries.append((f"{sim.name} official music video", sim.name))

        # PASO 3: último fallback
        if not queries:
            return self._fallback(title, artist)

        return queries[:10]

    def _extract_song_title(self, title: str, artist: str) -> str:
        """Extrae solo el título de la canción sin el artista."""
        clean = re.sub(
            r"\s*[\(\[]?(official\s*(music\s*)?video|lyric\s*video|audio|hd|hq|mv|lyrics|live)[\)\]]?",
            "", title, flags=re.IGNORECASE
        ).strip()
        for sep in [" - ", " \u2013 ", " | ", " : "]:
            if sep in clean:
                parts = clean.split(sep)
                # Si la primera parte es el artista, devuelve la segunda
                if artist.lower() in parts[0].lower():
                    return parts[1].strip()
                return parts[1].strip() if len(parts) > 1 else clean
        return clean

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

# ── Redis Cache ────────────────────────────────────────────────────
REDIS_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
CACHE_TTL   = 60 * 60 * 24  # 24 horas

def redis_get(key: str):
    """Obtiene valor de Redis. Retorna None si no existe o falla."""
    if not REDIS_URL:
        return None
    try:
        resp = req.get(
            f"{REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
            timeout=3
        )
        data = resp.json()
        return data.get("result")
    except Exception:
        return None

def redis_set(key: str, value: str, ttl: int = CACHE_TTL) -> bool:
    """Guarda valor en Redis con TTL en segundos."""
    if not REDIS_URL:
        return False
    try:
        req.post(
            f"{REDIS_URL}/set/{key}",
            headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
            json={"value": value, "ex": ttl},
            timeout=3
        )
        return True
    except Exception:
        return False


class YouTubeFetcher:
    CACHE_TTL  = 60 * 60 * 24
    # Fallback local si Redis no está disponible
    _local: dict = {}

    def __init__(self, max_per_query: int = 5):
        self.max_per_query = max_per_query

    def _key(self, q: str) -> str:
        return f"sonar:yt:{hashlib.md5(q.encode()).hexdigest()}"

    def _cache_get(self, key: str):
        # Intenta Redis primero
        val = redis_get(key)
        if val:
            try:
                return json.loads(val)
            except Exception:
                pass
        # Fallback local
        entry = self._local.get(key)
        if entry and time.time() - entry.get("ts", 0) < self.CACHE_TTL:
            return entry.get("data")
        return None

    def _cache_set(self, key: str, data: list) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        # Guarda en Redis
        redis_set(key, payload, self.CACHE_TTL)
        # Guarda local como fallback
        self._local[key] = {"ts": time.time(), "data": data}

    def fetch_many(self, queries: list[tuple[str, str]]) -> list[VideoResult]:
        results = []
        for query, target_artist in queries:
            results.extend(self._fetch_one(query, target_artist))
            time.sleep(0.3)
        return results

    def _fetch_one(self, query: str, target_artist: str,
                   retries: int = 3) -> list[VideoResult]:
        key = self._key(query)
        cached = self._cache_get(key)
        if cached:
            return [VideoResult(**{**v, "target_artist": target_artist})
                    for v in cached]
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
                self._cache_set(key, [v.__dict__ for v in videos])
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
                         original_artist: str,
                         tags: list[str] = []) -> list[VideoResult]:
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
            if vid_id in seen_ids:
                continue
            # Verifica duplicados por título normalizado
            if title_key and title_key in seen_titles:
                continue

            ch_key = self._norm(v.channel)
            if artist_count[ch_key] >= self.MAX_PER_ARTIST:
                continue

            seen_ids.add(vid_id)
            if title_key:
                seen_titles.add(title_key)
            artist_count[ch_key] += 1
            v.score = self._score(v, tags)
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

    def _score(self, v: VideoResult, tags: list[str] = []) -> float:
        score = 0.0
        t  = v.title.lower()
        ch = self._norm(v.channel)

        # Bonus si el canal o título coincide con el artista objetivo
        if v.target_artist.lower() in ch:
            score += 3.0
        if v.target_artist.lower() in t:
            score += 1.5

        # Bonus por tags de la canción original encontrados en el título
        for tag in tags:
            if tag in t:
                score += 0.5

        # Popularidad neutra
        if v.view_count > 0:
            score += min(math.log10(v.view_count) / 10, 0.5)

        # Penaliza mixes y compilaciones
        if any(w in t for w in ["mix", "compilation", "top 10", "best of", "all songs"]):
            score -= 1.5

        return round(score, 3)


# ══════════════════════════════════════════════════════════════════
# RECOMENDADOR
# ══════════════════════════════════════════════════════════════════

resolver  = URLResolver()
query_gen = SmartQueryGenerator()
fetcher   = YouTubeFetcher(max_per_query=5)
scorer    = FilterScorer()
genius    = GeniusClient()

def recommend(raw_input: str, artist: str, n: int = 10) -> dict:
    title, artist = resolver.resolve(raw_input, artist)
    queries = query_gen.generate(title, artist)
    raw     = fetcher.fetch_many(queries)

    # Obtener tags de la canción para afinar el scorer
    song_title = query_gen._extract_song_title(title, artist)
    tags = []
    if song_title:
        tags = query_gen.lastfm.get_track_tags(artist, song_title)

    ranked  = scorer.filter_and_score(raw, artist, tags)
    top     = ranked[:n]

    def fmt(r):
        return {
            "title":         r.title,
            "url":           r.url,
            "duration":      r.duration_fmt(),
            "channel":       r.channel,
            "target_artist": r.target_artist,
            "score":         r.score,
        }

    return {
        "title":      title,
        "artist":     artist,
        "tags":       tags[:5],
        "top":        [fmt(r) for r in top[:5]],
        "secondary":  [fmt(r) for r in top[5:]],
        "results":    [fmt(r) for r in top],
    }


# ══════════════════════════════════════════════════════════════════
# RUTAS FLASK
# ══════════════════════════════════════════════════════════════════

STYLES = {
    "heavy": {
        "label": "Guitarras pesadas",
        "icon": "🎸",
        "seeds": ["Deftones", "Tool", "Queens of the Stone Age", "Soundgarden"]
    },
    "atmospheric": {
        "label": "Atmosférico",
        "icon": "🌊",
        "seeds": ["Slowdive", "Beach House", "Cocteau Twins", "Grouper"]
    },
    "electronic": {
        "label": "Electrónico",
        "icon": "🤖",
        "seeds": ["Burial", "Four Tet", "Massive Attack", "Boards of Canada"]
    },
    "rhythmic": {
        "label": "Con ritmo",
        "icon": "🥁",
        "seeds": ["Rage Against the Machine", "Prodigy", "Daft Punk"]
    },
    "melodic": {
        "label": "Melódico",
        "icon": "🎹",
        "seeds": ["Bon Iver", "Nils Frahm", "Sigur Ros", "Olafur Arnalds"]
    },
    "dark": {
        "label": "Oscuro",
        "icon": "🌙",
        "seeds": ["Nine Inch Nails", "Portishead", "Crystal Castles", "The Cure"]
    },
    "bright": {
        "label": "Luminoso",
        "icon": "☀️",
        "seeds": ["MGMT", "Vampire Weekend", "Phoenix", "Two Door Cinema Club"]
    },
    "urban": {
        "label": "Urbano",
        "icon": "🎤",
        "seeds": ["Bad Bunny", "Kendrick Lamar", "Tyler the Creator", "Feid"]
    },
}

@app.route("/explore", methods=["POST"])
def explore():
    data  = request.get_json()
    style = data.get("style", "")
    if style not in STYLES:
        return jsonify({"error": "Estilo no válido"}), 400
    try:
        cfg    = STYLES[style]
        artist = random.choice(cfg["seeds"])
        result = recommend(artist, artist)
        result["style_label"] = cfg["label"]
        result["style_icon"]  = cfg["icon"]
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/solo", methods=["POST"])
def solo():
    """Busca canciones del mismo artista — sin recomendaciones externas."""
    data   = request.get_json()
    artist = data.get("artist", "").strip()
    if not artist:
        return jsonify({"error": "Artista requerido"}), 400
    try:
        tracks = query_gen.lastfm.get_top_tracks(artist, limit=10)
        queries = []
        if tracks:
            random.shuffle(tracks)
            for track in tracks[:8]:
                queries.append((f"{artist} {track} official", artist))
        else:
            queries.append((f"{artist} official music video", artist))

        raw    = fetcher.fetch_many(queries)
        ranked = scorer.filter_and_score(raw, "")
        top    = ranked[:10]

        def fmt(r):
            return {
                "title":         r.title,
                "url":           r.url,
                "duration":      r.duration_fmt(),
                "channel":       r.channel,
                "target_artist": artist,
                "score":         r.score,
            }

        return jsonify({
            "title":     artist,
            "artist":    artist,
            "top":       [fmt(r) for r in top[:5]],
            "secondary": [fmt(r) for r in top[5:]],
            "results":   [fmt(r) for r in top],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/resolve", methods=["POST"])
def resolve():
    """Solo detecta el artista de una URL o texto — sin buscar recomendaciones."""
    data   = request.get_json()
    query  = data.get("query", "").strip()
    artist = data.get("artist", "").strip()
    try:
        title, detected_artist = resolver.resolve(query, artist)
        return jsonify({"title": title, "artist": detected_artist})
    except Exception as e:
        return jsonify({"artist": artist or query}), 200

@app.route("/gems", methods=["POST"])
def gems():
    """
    Encuentra joyas ocultas basadas en el historial del usuario.
    Usa Last.fm para artistas del género + Genius para medir obsesión real.
    """
    data    = request.get_json()
    history = data.get("history", [])  # artistas del historial

    if not history:
        # Sin historial, elige género aleatorio
        history = ["Deftones", "Mora", "Bad Bunny", "Crystal Castles"]

    try:
        # 1. Obtiene artistas similares a los del historial via Last.fm
        similar_artists = []
        sample = random.sample(history, min(3, len(history)))
        for artist in sample:
            similar = query_gen.lastfm.get_similar_artists(artist, limit=8)
            for s in similar:
                # Solo artistas con match medio — no los más famosos
                if 0.1 < s.match < 0.6:
                    similar_artists.append(s.name)

        if not similar_artists:
            similar_artists = history

        # Deduplica y mezcla
        similar_artists = list(set(similar_artists))
        random.shuffle(similar_artists)

        # 2. Busca joyas en Genius
        gems_list = genius.get_hidden_gems(similar_artists, limit=8)

        if not gems_list:
            return jsonify({"error": "No se encontraron joyas. Intenta de nuevo."}), 404

        # 3. Busca cada joya en YouTube
        results = []
        for gem in gems_list[:5]:
            query   = f"{gem['artist']} {gem['title']} official"
            videos  = fetcher._fetch_one(query, gem['artist'])
            ranked  = scorer.filter_and_score(videos, "")
            if ranked:
                r = ranked[0]
                results.append({
                    "title":         r.title,
                    "url":           r.url,
                    "duration":      r.duration_fmt(),
                    "channel":       r.channel,
                    "target_artist": gem['artist'],
                    "score":         r.score,
                    "gem_score":     round(gem['score'], 2),
                    "annotations":   gem['annotations'],
                    "pageviews":     gem['pageviews'],
                })

        if not results:
            return jsonify({"error": "No se encontraron joyas en YouTube."}), 404

        return jsonify({"results": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/ads.txt")
def ads_txt():
    return "google.com, pub-7088507477090236, DIRECT, f08c47fec0942fa0", 200, {"Content-Type": "text/plain"}

# ── Likes ─────────────────────────────────────────────────────────

def _week_key(song_key: str) -> str:
    """Genera clave Redis con número de semana actual."""
    from datetime import date
    week = date.today().isocalendar()[1]
    year = date.today().year
    return f"sonar:likes:{year}W{week:02d}:{song_key}"

def _song_key(title: str, artist: str) -> str:
    """Clave única por canción."""
    raw = f"{title}:{artist}".lower()
    return hashlib.md5(raw.encode()).hexdigest()[:16]

@app.route("/like", methods=["POST"])
def like():
    data   = request.get_json()
    title  = data.get("title", "").strip()
    artist = data.get("target_artist", "").strip()
    url    = data.get("url", "").strip()
    if not title or not artist:
        return jsonify({"error": "Datos incompletos"}), 400
    try:
        sk  = _song_key(title, artist)
        key = _week_key(sk)
        # Incrementa contador semanal
        val = redis_get(key)
        count = int(val) if val else 0
        count += 1
        redis_set(key, str(count), 60 * 60 * 24 * 8)  # 8 días TTL
        # Guarda metadata de la canción para el top
        meta_key = f"sonar:meta:{sk}"
        redis_set(meta_key, json.dumps({
            "title": title, "artist": artist, "url": url
        }), 60 * 60 * 24 * 30)
        return jsonify({"likes": count, "song_key": sk})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/likes/<song_key>", methods=["GET"])
def get_likes(song_key):
    """Obtiene el contador de likes de una canción."""
    try:
        key = _week_key(song_key)
        val = redis_get(key)
        return jsonify({"likes": int(val) if val else 0})
    except Exception:
        return jsonify({"likes": 0})

@app.route("/trending", methods=["GET"])
def trending():
    """Devuelve el top 10 de canciones más likeadas esta semana."""
    try:
        from datetime import date
        week = date.today().isocalendar()[1]
        year = date.today().year
        prefix = f"sonar:likes:{year}W{week:02d}:"

        # Busca todas las claves de esta semana en Redis
        if not REDIS_URL:
            return jsonify({"songs": []})

        resp = req.get(
            f"{REDIS_URL}/keys/{prefix}*",
            headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
            timeout=5
        )
        keys = resp.json().get("result", [])

        songs = []
        for key in keys:
            val = redis_get(key)
            if not val:
                continue
            sk = key.replace(f"{prefix}", "")
            meta_val = redis_get(f"sonar:meta:{sk}")
            if not meta_val:
                continue
            try:
                meta = json.loads(meta_val)
                songs.append({
                    "title":  meta.get("title", ""),
                    "artist": meta.get("artist", ""),
                    "url":    meta.get("url", ""),
                    "likes":  int(val),
                })
            except Exception:
                continue

        # Ordena por likes descendente
        songs.sort(key=lambda x: x["likes"], reverse=True)
        return jsonify({"songs": songs[:10]})
    except Exception as e:
        return jsonify({"songs": [], "error": str(e)})

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
    ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
    if not check_rate_limit(ip):
        return jsonify({"error": "Demasiadas búsquedas. Espera un momento antes de continuar."}), 429
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

#!/usr/bin/env python3
"""jellyfeed — met le contenu de ton serveur Jellyfin sur l'accueil webOS.

Tourne sur la TV (root). Lit config.json (session Quick Connect obtenue par
l'app JellyHome), interroge Jellyfin et écrit, dans le dossier de données :

  - des réponses SDP toutes faites (bandeau, rangées) au format de l'accueil LG ;
  - rules.json, que libhomepatch relit à chaud pour les servir à l'accueil.

Les URL d'images Jellyfin sont publiques : le jeton ne quitte pas config.json.

    jellyfeed.py daemon            boucle (rafraîchit toutes les 10 min)
    jellyfeed.py once              une passe
    jellyfeed.py discover          serveurs Jellyfin du réseau (JSON)
    jellyfeed.py set-config B64    fusionne un objet JSON (base64) dans config.json
    jellyfeed.py status            état (JSON, sans le jeton)
"""
import base64
import hashlib
import http.server
import json
import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zlib

DATA = os.environ.get("HOMEPATCH_DIR", "/media/developer/jellyhome")
CONFIG = os.path.join(DATA, "config.json")
USER_RULES = os.path.join(DATA, "user-rules.json")
STATUS = os.path.join(DATA, "status.json")
REFRESH = 600
SDX = "luna://com.webos.service.sdx/send"
RESP = "/serverResponse/response"
JELLYFIN_APP = "org.jellyfin.webos"

# Catégories Jellyfin servables au bandeau ou en rangée ; "lg" = contenu LG
# d'origine, "none" = rien.
CATEGORIES = ("mix", "resume", "nextUp", "latest", "favorites", "random")

DEFAULT_OPTIONS = {
    # Deux zones fixes de l'accueil, chacune remplaçable par une catégorie Jellyfin.
    # Le contenu LG remplacé peut redescendre en rangée (déplaçable comme les autres).
    "topSource": "latest",  # grand carrousel du haut (emplacement pub) et rangée « editorsPick » LG
    "topLgRow": True,       #   … son contenu LG en rangée
    "heroSource": "resume", # bandeau à côté des entrées récentes (LG y met le direct)
    "underRow": "lg",       #   … rangée sous ce bandeau : LG d'origine, une catégorie, ou rien
    "resume": True,         # rangées
    "nextUp": True,
    "latest": True,
    "hideAds": True,        # pubs LG masquées (comme si on les coupait dans les réglages)
    "progress": True,       # barre de progression sur « Reprendre »
    # Images des épisodes : celles de la série (défaut) ou de l'épisode, par rôle
    "episodeImages": {"top": "series", "hero": "series", "under": "series", "resume": "series",
                      "nextUp": "series", "latest": "series"},
    "adTrailers": True,     # bandes-annonces Jellyfin préchargées, lues dans le carrousel du haut
}
ADMANAGER = "com.webos.service.admanager/requestBannerInfoWithoutContextIndex"
LAUNCH = os.path.join(DATA, "launch.json")
# Réponse du gestionnaire de pub quand les pubs sont coupées dans les réglages LG
NO_AD = {"returnValue": False, "errorCode": "AD.ERR.13", "errorText": "Not Valid Condition"}

TEXTS = {
    "fr": {"mix": "Jellyfin", "resume": "Reprendre", "nextUp": "À suivre", "latest": "Derniers ajouts",
           "favorites": "Favoris", "random": "À découvrir", "trailer": "Bande-annonce"},
    "en": {"mix": "Jellyfin", "resume": "Continue watching", "nextUp": "Next up", "latest": "Recently added",
           "favorites": "Favorites", "random": "Discover", "trailer": "Trailer"},
    "de": {"mix": "Jellyfin", "resume": "Weiterschauen", "nextUp": "Als Nächstes", "latest": "Neu hinzugefügt",
           "favorites": "Favoriten", "random": "Entdecken", "trailer": "Trailer"},
    "es": {"mix": "Jellyfin", "resume": "Seguir viendo", "nextUp": "A continuación", "latest": "Añadido recientemente",
           "favorites": "Favoritos", "random": "Descubrir", "trailer": "Tráiler"},
    "it": {"mix": "Jellyfin", "resume": "Continua a guardare", "nextUp": "Prossimi", "latest": "Aggiunti di recente",
           "favorites": "Preferiti", "random": "Scopri", "trailer": "Trailer"},
}


def text(cfg, key, suffix=True):
    lang = (cfg.get("lang") or "fr")[:2].lower()
    t = TEXTS.get(lang, TEXTS["en"])[key]
    return t if key == "mix" or not suffix else t + " · Jellyfin"


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj, private=False):
    """Écriture atomique ; ne touche pas le fichier si le contenu est identique
    (sinon libhomepatch rechargerait les règles pour rien)."""
    txt = json.dumps(obj, ensure_ascii=False, indent=1)
    try:
        with open(path) as f:
            if f.read() == txt:
                return False
    except OSError:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(txt)
    if private:
        os.chmod(tmp, 0o600)
    os.rename(tmp, path)
    return True


def options(cfg):
    o = dict(DEFAULT_OPTIONS)
    o.update(cfg.get("options") or {})
    # Anciennes options booléennes (0.1.0)
    if o.get("hero") is False:
        o["heroSource"] = "lg"
    if o.get("lgLiveRow") is False and o["underRow"] == "lg":
        o["underRow"] = "none"
    o.pop("hero", None)
    o.pop("lgLiveRow", None)
    ep = dict(DEFAULT_OPTIONS["episodeImages"])
    ep.update(o.get("episodeImages") or {})
    o["episodeImages"] = ep
    return o


# ------------------------------------------------------------- Jellyfin

class Jellyfin:
    def __init__(self, cfg):
        self.base = cfg["server"].rstrip("/")
        self.user = cfg["userId"]
        self.auth = ('MediaBrowser Client="JellyHome", Device="LG webOS TV", '
                     'DeviceId="%s", Version="0.1.0", Token="%s"'
                     % (cfg.get("deviceId", "jellyhome"), cfg["token"]))

    def get(self, path, **q):
        url = self.base + path + ("?" + urllib.parse.urlencode(q) if q else "")
        req = urllib.request.Request(url, headers={"Authorization": self.auth,
                                                   "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)

    def post(self, path, **q):
        url = self.base + path + ("?" + urllib.parse.urlencode(q) if q else "")
        req = urllib.request.Request(url, data=b"", method="POST",
                                     headers={"Authorization": self.auth})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status

    def img(self, item_id, kind, tag, width, index=None):
        path = "/Items/%s/Images/%s" % (item_id, kind)
        if index is not None:
            path += "/%d" % index
        return "%s%s?%s" % (self.base, path, urllib.parse.urlencode(
            {"tag": tag, "maxWidth": width, "quality": 90}))

    def landscape(self, it, width, episode_mode="series"):
        """Vignette, sinon image de fond, sinon affiche. Pour un épisode, celles de
        la série par défaut ; en mode "episode", sa capture d'abord."""
        tags = it.get("ImageTags") or {}
        series = [
            (it.get("SeriesId"), "Thumb", it.get("SeriesThumbImageTag"), None),
            (it.get("ParentThumbItemId"), "Thumb", it.get("ParentThumbImageTag"), None),
            (it.get("ParentBackdropItemId"), "Backdrop", (it.get("ParentBackdropImageTags") or [None])[0], 0),
            (it.get("SeriesId"), "Primary", it.get("SeriesPrimaryImageTag"), None),
        ]
        own = [
            (it.get("Id"), "Thumb", tags.get("Thumb"), None),
            (it.get("Id"), "Backdrop", (it.get("BackdropImageTags") or [None])[0], 0),
            (it.get("Id"), "Primary", tags.get("Primary"), None),
        ]
        if it.get("Type") != "Episode":
            choices = own + series
        elif episode_mode == "episode":
            # La capture d'un épisode tient lieu de vignette
            choices = [(it.get("Id"), "Primary", tags.get("Primary"), None)] + series + own
        else:
            choices = series + own
        for iid, kind, tag, index in choices:
            if iid and tag:
                return self.img(iid, kind, tag, width, index)
        return None

    def download(self, path, dest, limit=None, **q):
        """Fichier Jellyfin → dest (écriture atomique), tronqué à limit octets."""
        url = self.base + path + ("?" + urllib.parse.urlencode(q) if q else "")
        req = urllib.request.Request(url, headers={"Authorization": self.auth})
        tmp, size = dest + ".part", 0
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                size += len(chunk)
                if limit and size >= limit:
                    break
        os.rename(tmp, dest)
        return size

    def fetch_bytes(self, path, **q):
        url = self.base + path + ("?" + urllib.parse.urlencode(q) if q else "")
        req = urllib.request.Request(url, headers={"Authorization": self.auth})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()


def backdrop_ref(it):
    """(élément, tag) de l'image de fond, celle de la série pour un épisode."""
    own = (it.get("Id"), (it.get("BackdropImageTags") or [None])[0])
    parent = (it.get("ParentBackdropItemId"), (it.get("ParentBackdropImageTags") or [None])[0])
    for iid, tag in ((parent, own) if it.get("Type") == "Episode" else (own, parent)):
        if iid and tag:
            return iid, tag
    return None, None


def poster_ref(it):
    """(élément, tag) de l'affiche, celle de la série pour un épisode."""
    if it.get("Type") == "Episode" and it.get("SeriesId") and it.get("SeriesPrimaryImageTag"):
        return it["SeriesId"], it["SeriesPrimaryImageTag"]
    tag = (it.get("ImageTags") or {}).get("Primary")
    return (it["Id"], tag) if tag else (None, None)


def logo_ref(it):
    """(élément, tag) du logo-titre (PNG transparent), celui de la série pour un épisode."""
    tags = it.get("ImageTags") or {}
    if tags.get("Logo"):
        return it["Id"], tags["Logo"]
    if it.get("ParentLogoItemId") and it.get("ParentLogoImageTag"):
        return it["ParentLogoItemId"], it["ParentLogoImageTag"]
    return None, None


FIELDS = ("BackdropImageTags,ParentBackdropImageTags,ImageTags,ParentThumbImageTag,"
          "SeriesThumbImageTag,SeriesPrimaryImageTag,ParentLogoImageTag,LocalTrailerCount,RemoteTrailers")


def title(it):
    if it.get("Type") == "Episode":
        return "%s · S%dE%d · %s" % (it.get("SeriesName", ""), it.get("ParentIndexNumber") or 0,
                                     it.get("IndexNumber") or 0, it.get("Name", ""))
    year = it.get("ProductionYear")
    return "%s (%s)" % (it.get("Name", ""), year) if year else it.get("Name", "")


# La barre de progression n'existe que pour les programmes en direct : l'accueil
# la calcule avec (maintenant - début) / (fin - début). On présente donc un
# élément en cours comme un « programme » dont l'avancement est la position de
# lecture. Durées étirées ×1000 pour que la barre ne bouge pas entre deux rafraîchissements.
STRETCH = 1000


def progress_window(it):
    ud = it.get("UserData") or {}
    pos, total = ud.get("PlaybackPositionTicks") or 0, it.get("RunTimeTicks") or 0
    if not pos or not total or pos >= total:
        return None
    now = time.time()
    fmt = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    return fmt(now - pos / 1e7 * STRETCH), fmt(now + (total - pos) / 1e7 * STRETCH)


def card(jf, it, w, h, episode_mode="series", progress=False):
    """Un élément au format des étagères LG."""
    url, url4k = jf.landscape(it, w, episode_mode), jf.landscape(it, w * 2, episode_mode)
    if not url:
        return None
    c = {
        "type": "vod",
        "titleText": title(it),
        "image": {"url": url, "width": w, "height": h},
        "image_4k": {"url": url4k, "width": w * 2, "height": h * 2},
        "onClick": {"targetAppId": JELLYFIN_APP, "contentId": it["Id"]},
    }
    win = progress and progress_window(it)
    if win:
        c["type"] = "live"
        c["onClick"].update(startTime=win[0], endTime=win[1], livepip=False)
    return c


def editors_pick(title_text, items):
    """Réponse sdx/send de la zone du haut (même forme que « editorsPick » LG)."""
    return {"returnValue": True,
            "serverResponse": {"code": "200", "message": "OK", "response": json.dumps({
                "editorsPick": {"shelfTitle": title_text, "itemList": items,
                                "recommendId": "jellyhome-" + time.strftime("%Y%m%d%H%M")}},
                ensure_ascii=False)}}


def lg_top_row():
    """Contenu LG de la zone du haut, remis en forme de rangée ordinaire."""
    d = read_json(os.path.join(DATA, "lg-top.json"))
    try:
        ep = json.loads(d["serverResponse"]["response"])["editorsPick"]
        if not ep.get("itemList"):
            return False
        write_json(os.path.join(DATA, "lgtop-row.json"), {
            "returnValue": True, "serverResponse": {"code": "200", "message": "OK",
                                                    "response": json.dumps(ep, ensure_ascii=False)}})
        return True
    except (TypeError, KeyError, ValueError):
        return False


def shelf(title_text, items):
    """Réponse sdx/send complète, telle que la renvoie le serveur LG."""
    return {"returnValue": True,
            "serverResponse": {"code": "200", "message": "OK", "response": json.dumps({
                "shelfTitle": title_text, "expirationSpan": REFRESH,
                "recommendId": "jellyhome-" + time.strftime("%Y%m%d%H%M"),
                "itemList": items}, ensure_ascii=False)}}


DRAWN = os.path.join(DATA, "drawn.json")  # tirages aléatoires en cours : {catégorie: [heure, éléments]}
DRAW_FOR = 3 * 3600                        # durée d'un tirage


def fetch(jf, cat):
    u = "/Users/%s" % jf.user
    common = {"Fields": FIELDS, "EnableImageTypes": "Thumb,Backdrop,Primary,Logo"}
    if cat == "resume":
        return jf.get(u + "/Items/Resume", Limit=20, MediaTypes="Video", **common).get("Items", [])
    if cat == "nextUp":
        return jf.get("/Shows/NextUp", UserId=jf.user, Limit=20, **common).get("Items", [])
    if cat == "latest":
        return jf.get(u + "/Items/Latest", Limit=20, IncludeItemTypes="Movie,Series", **common)
    if cat in ("favorites", "random"):
        # Tirage gardé un moment, sinon chaque rafraîchissement (un par visuel
        # préparé) rebattrait les cartes. Gardé dans un fichier : la passe « once » du démarrage et le démon
        # doivent montrer les mêmes éléments.
        drawn = read_json(DRAWN, {})
        if drawn.get("fields") != FIELDS:  # tirage fait avec d'autres champs : à refaire
            drawn = {"fields": FIELDS}
        at, items = drawn.get(cat) or (0, None)
        if items is not None and time.time() - at < DRAW_FOR:
            return items
        q = dict(common, Recursive="true", IncludeItemTypes="Movie,Series", SortBy="Random", Limit=20)
        if cat == "favorites":
            q["Filters"] = "IsFavorite"
        items = jf.get(u + "/Items", **q).get("Items", [])
        drawn[cat] = [time.time(), items]
        write_json(DRAWN, drawn)
        return items
    if cat == "mix":
        return fetch(jf, "resume") + fetch(jf, "latest")
    return []


def cards(jf, items, w, h, limit, episode_mode="series", progress=False):
    out, seen = [], set()
    for it in items:
        if it["Id"] in seen:
            continue
        c = card(jf, it, w, h, episode_mode, progress)
        if c:
            seen.add(it["Id"])
            out.append(c)
        if len(out) >= limit:
            break
    return out


# ------------------------------------------- carrousel publicitaire du haut
#
# L'accueil demande au gestionnaire de pub les visuels de « Portal/HomeBigCarousel »
# et les fait tourner. On lui répond à la place avec nos éléments. Une pub vidéo
# s'y décrit en deux actifs de même sequenceId : la vidéo, jouée sur la gauche
# (46 % de la largeur), et une image pleine largeur dont la partie droite reste
# visible. Pour un élément qui a une bande-annonce, on fabrique donc cette image :
# le fond de l'élément réduit sur la droite, avec son logo-titre par-dessus.
# Bandes-annonces et images sont préparées à l'avance (fichiers locaux, comme les
# pubs LG en cache) : n'apparaît au carrousel que ce qui est prêt à être lu.

AD_DIR = os.path.join(DATA, "ad")
AD_FILE = "ad/carousel.json"
AD_MAP = os.path.join(AD_DIR, "map.json")
ADCLICK = os.path.join(DATA, "adclick.json")
ADMANAGER_BASE = "com.webos.service.admanager/"
AD_SLOT = "HomeBigCarousel"
AD_W, AD_H, AD_SPLIT = 1629, 420, 747   # taille de l'emplacement ; largeur couverte par la vidéo
AD_ID = 770000000                       # identifiants de nos actifs (770000001…), reconnus au clic
AD_ITEMS = 10
TRAILER_MAX = 40 << 20                  # octets gardés d'une bande-annonce (MP4 fragmenté : lisible tronqué)
TRAILER_SECONDS = 150                   # durée de lecture maximale annoncée à l'accueil
YTDLP = os.path.join(DATA, "yt-dlp")    # téléchargé au premier besoin, mis à jour chaque semaine
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
YTDLP_PINNED = "https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp"  # dernière testée (Python 3.10)
PYLIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pylib")
BG = (11, 11, 16)                       # fond de la zone vidéo
POSTER_WIDEN = 1.04                     # élargissement de l'affiche
LOGO_H = 140                            # hauteur maximale du logo-titre
CROP_Y = 0.2                            # recadrage vertical : 0 haut, 0.5 centre, 1 bas


def png_decode(data):
    """PNG 8 bits non entrelacé → (largeur, hauteur, pixels RGBA). None sinon."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, plte, trns = 8, [], None, None
    w = h = ctype = 0
    while pos < len(data):
        n, kind = int.from_bytes(data[pos:pos + 4], "big"), data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            w, h = int.from_bytes(chunk[0:4], "big"), int.from_bytes(chunk[4:8], "big")
            depth, ctype, interlace = chunk[8], chunk[9], chunk[12]
            if depth != 8 or interlace or ctype not in (0, 2, 3, 4, 6):
                return None
        elif kind == b"PLTE":
            plte = chunk
        elif kind == b"tRNS":
            trns = chunk
        elif kind == b"IDAT":
            idat.append(chunk)
        elif kind == b"IEND":
            break
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw, stride = zlib.decompress(b"".join(idat)), w * bpp
    out, prev, p = bytearray(), bytearray(stride), 0
    for _ in range(h):
        ft, row = raw[p], bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if ft == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 255
        elif ft == 2:
            row = bytearray((a + b) & 255 for a, b in zip(row, prev))
        elif ft == 3:
            for i in range(stride):
                row[i] = (row[i] + (((row[i - bpp] if i >= bpp else 0) + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b, c = prev[i], prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += row
        prev = row
    if ctype == 6:
        return w, h, out
    rgba = bytearray(w * h * 4)
    if ctype == 2:
        rgba[0::4], rgba[1::4], rgba[2::4] = out[0::3], out[1::3], out[2::3]
        rgba[3::4] = b"\xff" * (w * h)
    elif ctype in (0, 4):
        g = out[0::bpp]
        rgba[0::4] = rgba[1::4] = rgba[2::4] = g
        rgba[3::4] = out[1::2] if ctype == 4 else b"\xff" * (w * h)
    else:
        alpha = bytes(trns or b"") + b"\xff" * 256
        for i, v in enumerate(out):
            rgba[i * 4:i * 4 + 4] = bytes(plte[v * 3:v * 3 + 3]) + alpha[v:v + 1]
    return w, h, rgba


def png_encode(w, h, rgb):
    def chunk(kind, body):
        return (len(body).to_bytes(4, "big") + kind + body
                + zlib.crc32(kind + body).to_bytes(4, "big"))
    stride = w * 3
    raw = b"".join(b"\0" + bytes(rgb[y * stride:(y + 1) * stride]) for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", w.to_bytes(4, "big") + h.to_bytes(4, "big")
                                         + bytes((8, 2, 0, 0, 0)))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


class Font:
    """Glyphes pré-rendus par tools/make-font.py (couverture 0-255)."""
    _cache = {}

    def __init__(self, size):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "font-%d" % size)
        m = read_json(base + ".json")
        with open(base + ".bin", "rb") as f:
            self.px = zlib.decompress(f.read())
        self.width, self.height, self.glyphs = m["width"], m["height"], m["glyphs"]

    @classmethod
    def get(cls, size):
        if size not in cls._cache:
            cls._cache[size] = cls(size)
        return cls._cache[size]

    def measure(self, txt):
        return sum(self.glyphs.get(c, self.glyphs["?"])[2] for c in txt)

    def wrap(self, txt, width, lines):
        """Coupe aux espaces en au plus `lines` lignes ; « … » si ça déborde."""
        out, cur = [], ""
        for word in txt.split():
            cand = (cur + " " + word).strip()
            if self.measure(cand) <= width or not cur:
                cur = cand
            else:
                out.append(cur)
                cur = word
        out.append(cur)
        if len(out) > lines:
            out = out[:lines]
            out[-1] += "…"
        for i, line in enumerate(out):
            while self.measure(line) > width and len(line) > 1:
                line = line[:-2] + "…"
            out[i] = line
        return out

    def draw(self, canvas, txt, x, y, color=(255, 255, 255), shadow=True):
        """Écrit txt dans le canevas RGB (AD_W de large), coin haut gauche (x, y)."""
        for dx, dy, col, k in ((2, 2, (0, 0, 0), 0.6), (0, 0, color, 1.0)) if shadow else ((0, 0, color, 1.0),):
            cx = x + dx
            for ch in txt:
                gx, gw, adv, left = self.glyphs.get(ch, self.glyphs["?"])
                for gy in range(self.height):
                    py = y + dy + gy
                    if not 0 <= py < AD_H:
                        continue
                    src = gy * self.width + gx
                    for i in range(gw):
                        a = self.px[src + i]
                        px_ = cx + left + i
                        if not a or not 0 <= px_ < AD_W:
                            continue
                        a = a * k / 255
                        d = (py * AD_W + px_) * 3
                        for c in range(3):
                            canvas[d + c] = int(col[c] * a + canvas[d + c] * (1 - a))
                cx += adv


def resize(img, w, h, cover=False):
    """Redimensionnement au plus proche voisin d'une image RGBA ; cover : remplit
    w × h en gardant les proportions, recadré au centre en largeur et un peu sous
    le centre en hauteur (CROP_Y)."""
    sw, sh, px = img
    if (sw, sh) == (w, h):
        return img
    k = max(w / sw, h / sh) if cover else None
    vw, vh = (w / k, h / k) if cover else (sw, sh)  # zone source utilisée
    x0, y0 = (sw - vw) / 2, (sh - vh) * CROP_Y
    cols = [int(x0 + x * vw / w) * 4 for x in range(w)]
    out = bytearray()
    for y in range(h):
        row = int(y0 + y * vh / h) * sw * 4
        for c in cols:
            out += px[row + c:row + c + 4]
    return w, h, out


def paste(canvas, img, ox, oy, fade=0):
    """Copie une image RGBA dans le canevas RGB ; fade : fondu sur son bord gauche."""
    w, h, px = img
    for y in range(h):
        line = bytearray(w * 3)
        src = y * w * 4
        line[0::3], line[1::3], line[2::3] = (px[src:src + w * 4][k::4] for k in range(3))
        for x in range(min(fade, w)):
            t = x / fade
            for k in range(3):
                line[x * 3 + k] = int(BG[k] + (line[x * 3 + k] - BG[k]) * t)
        d = ((oy + y) * AD_W + ox) * 3
        canvas[d:d + w * 3] = line


def blend(canvas, img, ox, oy):
    """Pose une image RGBA (transparence comprise) dans le canevas RGB."""
    w, h, px = img
    for y in range(h):
        for x in range(w):
            s = (y * w + x) * 4
            a = px[s + 3]
            if a:
                d = ((oy + y) * AD_W + ox + x) * 3
                for k in range(3):
                    canvas[d + k] = (px[s + k] * a + canvas[d + k] * (255 - a)) // 255


def shade(canvas, x0, x1, y0, y1, strength):
    """Assombrit un bandeau en dégradé vertical : rien en y0, strength en y1."""
    for y in range(y0, y1):
        f = 1 - strength * (y - y0) / max(1, y1 - y0)
        d = (y * AD_W + x0) * 3
        canvas[d:d + (x1 - x0) * 3] = bytes(int(v * f) for v in canvas[d:d + (x1 - x0) * 3])


def fit(img, w, h):
    """Réduit une image pour qu'elle tienne dans w × h."""
    iw, ih, _ = img
    if iw <= w and ih <= h:
        return img
    k = min(w / iw, h / ih)
    return resize(img, max(1, int(iw * k)), max(1, int(ih * k)))


def compose_image(backdrop, logo, name, subtitle=None, poster=None):
    """Visuel d'un élément du carrousel, avec son titre : le logo de l'élément s'il
    en a un, sinon name en texte, et subtitle (l'épisode) en petit.

    Avec affiche : l'affiche entière sur toute la hauteur à gauche (une bande-annonce
    vient s'y poser), l'image de fond sur le reste, le titre dans l'angle en haut à
    droite. Sans : l'image en pleine largeur, titre en bas à gauche."""
    canvas = bytearray(bytes(BG) * (AD_W * AD_H))
    small, big = Font.get(34), Font.get(64)
    if not poster:
        if backdrop:
            paste(canvas, resize(backdrop, AD_W, AD_H, cover=True), 0, 0)
            shade(canvas, 0, AD_W, AD_H // 2, AD_H, 0.55)  # lisibilité du titre
        # Bloc titre empilé depuis le bas ; la bande du bas reste à l'accueil (texte « sponsorisé »).
        ox, bottom, width = 56, AD_H - 72, AD_W - AD_SPLIT - 112
        if subtitle:
            bottom -= small.height
            small.draw(canvas, small.wrap(subtitle, width, 1)[0], ox, bottom, (225, 225, 230))
            bottom -= 6
        if logo:
            logo = fit(logo, width, LOGO_H)
            blend(canvas, logo, ox, bottom - logo[1])
        else:
            for i, line in enumerate(reversed(big.wrap(name, width, 2))):
                big.draw(canvas, line, ox, bottom - (i + 1) * (big.height - 14))
        return png_encode(AD_W, AD_H, canvas)

    # Affiche à ses proportions, élargie de POSTER_WIDEN (à peine rognée en haut et en bas)
    pw = min(AD_SPLIT, int(poster[0] * AD_H / poster[1] * POSTER_WIDEN))
    poster = resize(poster, pw, AD_H, cover=True)
    pw = poster[0]
    paste(canvas, poster, 0, (AD_H - poster[1]) // 2)
    if backdrop:
        paste(canvas, resize(backdrop, AD_W - pw, AD_H, cover=True), pw, 0, fade=60)
        # Assombrit l'angle haut droit pour le titre
        for y in range(0, AD_H // 2):
            f = 0.55 * (1 - y / (AD_H // 2))
            x0 = AD_W - 760
            for x in range(x0, AD_W, 4):
                g = 1 - f * (x - x0) / 760
                d = (y * AD_W + x) * 3
                canvas[d:d + 12] = bytes(int(v * g) for v in canvas[d:d + 12])
    right, top, width = AD_W - 120, 36, 620  # à gauche de la flèche « › » de l'accueil
    if logo:
        logo = fit(logo, width, LOGO_H)
        blend(canvas, logo, right - logo[0], top)
        top += logo[1] + 8
    else:
        for line in big.wrap(name, width, 2):
            big.draw(canvas, line, right - big.measure(line), top)
            top += big.height - 14
        top += 8
    if subtitle:
        line = small.wrap(subtitle, width, 1)[0]
        small.draw(canvas, line, right - small.measure(line), top, (225, 225, 230))
    return png_encode(AD_W, AD_H, canvas)


class AdPreparer:
    """Prépare en tâche de fond bandes-annonces et images composées, une à la fois.
    on_ready est appelé quand un élément devient prêt (pour régénérer les règles)."""

    def __init__(self, on_ready=None):
        self.jobs, self.pending, self.on_ready = queue.PriorityQueue(), set(), on_ready
        self.count = 0
        threading.Thread(target=self._run, daemon=True).start()

    def want(self, key, fn):
        if key in self.pending:
            return
        self.pending.add(key)
        # Les images d'abord (quelques secondes), les bandes-annonces ensuite
        self.count += 1
        self.jobs.put((0 if key.endswith(".png") else 1, self.count, key, fn))

    def _run(self):
        try:  # calculs d'image en Python pur : passer après l'interface
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 15)
        except (AttributeError, OSError):
            pass
        while True:
            _, _, key, fn = self.jobs.get()
            try:
                fn()
                log("carrousel : prêt", key)
                if self.on_ready:
                    self.on_ready()
            except Exception as e:
                log("carrousel : %s : %s" % (key, e))
            finally:
                self.pending.discard(key)


PREPARER = None  # créé par le démon ; sans lui (commande « once »), rien n'est téléchargé
# Commande « once » (avant chaque relance de l'accueil, qui ne recharge les visuels
# qu'à son démarrage) : les images composées sont faites sur place jusqu'à cette heure.
SYNC_UNTIL = 0

# L'accueil ne lit pas les fichiers locaux (image noire) : le démon sert ad/ en HTTP.
AD_PORT = 8097
AD_URL = "http://127.0.0.1:%d/" % AD_PORT


class AdFiles(http.server.BaseHTTPRequestHandler):
    """Fichiers de ad/ (images et bandes-annonces), avec Range pour la vidéo."""

    def do_GET(self):
        name = os.path.basename(urllib.parse.urlparse(self.path).path)
        path = os.path.join(AD_DIR, name)
        if not name or name.endswith((".part", ".json")) or not os.path.isfile(path):
            self.send_error(404)
            return
        size = os.path.getsize(path)
        start, end = 0, size - 1
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else max(0, size - int(b))
            end = min(int(b), size - 1) if a and b else end
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        else:
            self.send_response(200)
        self.send_header("Content-Type", "video/mp4" if name.endswith(".mp4") else "image/png")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(left, 1 << 16))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def log_message(self, *a):
        pass


def serve_ad_files():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", AD_PORT), AdFiles)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def youtube_id(url):
    q = urllib.parse.urlparse(url or "")
    if q.hostname in ("youtu.be",):
        return q.path.strip("/") or None
    if q.hostname and q.hostname.endswith("youtube.com"):
        return (urllib.parse.parse_qs(q.query).get("v") or [None])[0]
    return None


def trailer_of(jf, it):
    """Bande-annonce de l'élément (ou de sa série) : la locale de Jellyfin s'il en a
    une ({"Id"…}), sinon la première YouTube de ses liens ({"youtube": id}), sinon None."""
    iid = it.get("SeriesId") if it.get("Type") == "Episode" else it.get("Id")
    if not iid:
        return None
    src = it
    if it.get("Type") == "Episode":
        src = jf.get("/Users/%s/Items/%s" % (jf.user, iid))
    if src.get("LocalTrailerCount"):
        trailers = jf.get("/Users/%s/Items/%s/LocalTrailers" % (jf.user, iid))
        if trailers:
            return trailers[0]
    for t in src.get("RemoteTrailers") or []:
        vid = youtube_id(t.get("Url"))
        if vid:
            return {"youtube": vid}
    return None


def trailer_file(trailer):
    return "trailer-%s.mp4" % (("yt-" + trailer["youtube"]) if "youtube" in trailer else trailer["Id"])


def trailer_seconds(trailer, path):
    if "youtube" in trailer:
        return (read_json(path[:-4] + ".json", {}) or {}).get("duration") or TRAILER_SECONDS
    return (trailer.get("RunTimeTicks") or 0) / 1e7 or TRAILER_SECONDS


def ytdlp(*args, timeout=600):
    """yt-dlp avec le Node.js de webOS pour les vérifications JavaScript de YouTube."""
    env = dict(os.environ, PYTHONPATH=PYLIB)
    return subprocess.run(["python3", YTDLP, "--no-warnings", "--js-runtimes", "node"] + list(args),
                          env=env, capture_output=True, text=True, timeout=timeout)


def ensure_ytdlp():
    """Installe yt-dlp, ou le remplace s'il a plus d'une semaine ; garde l'ancien si
    la nouvelle version ne tourne pas (Python de la TV trop ancien)."""
    try:
        fresh = time.time() - os.path.getmtime(YTDLP) < 7 * 86400
    except OSError:
        fresh = False
    if fresh:
        return
    for url in (YTDLP_URL, YTDLP_PINNED):
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(YTDLP + ".new", "wb") as f:
                f.write(r.read())
            ok = subprocess.run(["python3", YTDLP + ".new", "--version"], capture_output=True,
                                env=dict(os.environ, PYTHONPATH=PYLIB), timeout=60).returncode == 0
        except Exception as e:
            log("yt-dlp : %s : %s" % (url, e))
            ok = False
        if ok:
            os.rename(YTDLP + ".new", YTDLP)
            return
    if os.path.exists(YTDLP):
        os.utime(YTDLP)  # on réessaiera dans une semaine


def prepare_youtube(vid, dest):
    """Bande-annonce YouTube : vidéo H.264 (480p) et son AAC téléchargés à part,
    puis réunis (mux_fmp4)."""
    ensure_ytdlp()
    url = "https://www.youtube.com/watch?v=" + vid
    parts = {"v": dest + ".v.part", "a": dest + ".a.part"}
    try:
        # 480p (854 × 480) couvre les 747 × 420 px de la vidéo dans le carrousel ;
        # à défaut 720p, puis 1080p, puis ce qu'il y a
        r = ytdlp("-f", "/".join("bv*[vcodec^=avc1][height>=%d][height<=%d][protocol=https]" % r
                                 for r in ((420, 480), (481, 720), (721, 1080)))
                  + "/bv*[vcodec^=avc1][protocol=https]/bv*[protocol=https]", "--print", "%(duration)s",
                  "--no-simulate", "-o", parts["v"], url)
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1:])
        duration = float((r.stdout.strip().splitlines() or ["0"])[-1] or 0)
        r = ytdlp("-f", "ba[ext=m4a][protocol=https]", "-o", parts["a"], url)
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1:])
        mux_fmp4(parts["v"], parts["a"], dest)
        write_json(dest[:-4] + ".json", {"duration": duration})
    finally:
        for p in parts.values():
            try:
                os.remove(p)
            except OSError:
                pass


def boxes(f, start, end):
    """Boîtes MP4 entre start et end : [(type, début, taille, taille d'en-tête)]."""
    out, p = [], start
    while p + 8 <= end:
        f.seek(p)
        head = f.read(16)
        size, kind = int.from_bytes(head[:4], "big"), head[4:8].decode("latin-1")
        hdr = 8
        if size == 1:
            size, hdr = int.from_bytes(head[8:16], "big"), 16
        elif size == 0:
            size = end - p
        if size < hdr:
            break
        out.append((kind, p, size, hdr))
        p += size
    return out


def mp4_box(kind, payload):
    return (8 + len(payload)).to_bytes(4, "big") + kind.encode() + payload


def mux_fmp4(video, audio, dest):
    """Réunit une vidéo seule et un son seul, MP4 fragmentés (DASH, comme les sert
    YouTube), en un seul MP4 fragmenté, sans réencoder : un moov à deux pistes,
    puis les fragments (moof + mdat, gardés côte à côte : leurs décalages restent
    valables) dans l'ordre du temps. Remplace ffmpeg, absent de la TV."""
    tracks = []
    for tid, path in ((1, video), (2, audio)):
        f = open(path, "rb")
        top = boxes(f, 0, os.path.getsize(path))
        get = {k: (p, s, h) for k, p, s, h in top if k in ("ftyp", "moov")}
        mp, ms, mh = get["moov"]
        moov = {k: (p, s, h) for k, p, s, h in boxes(f, mp + mh, mp + ms)}
        tp, ts, th = moov["trak"]
        f.seek(tp)
        trak = bytearray(f.read(ts))
        # tkhd (track_ID) et mdhd (échelle de temps) dans la piste
        timescale = 1
        for k, p, s, h in boxes(f, tp + th, tp + ts):
            if k == "tkhd":
                f.seek(p + h)
                ver = f.read(1)[0]
                off = p - tp + h + (20 if ver == 1 else 12)
                trak[off:off + 4] = tid.to_bytes(4, "big")
            elif k == "mdia":
                for k2, p2, s2, h2 in boxes(f, p + h, p + s):
                    if k2 == "mdhd":
                        f.seek(p2 + h2)
                        ver = f.read(1)[0]
                        f.seek(p2 + h2 + (20 if ver == 1 else 12))
                        timescale = int.from_bytes(f.read(4), "big")
        trex = None
        if "mvex" in moov:
            xp, xs, xh = moov["mvex"]
            for k, p, s, h in boxes(f, xp + xh, xp + xs):
                if k == "trex":
                    f.seek(p)
                    trex = bytearray(f.read(s))
                    trex[h + 4:h + 8] = tid.to_bytes(4, "big")
        frags = []
        for i, (k, p, s, h) in enumerate(top):
            if k != "moof":
                continue
            t = 0
            for k2, p2, s2, h2 in boxes(f, p + h, p + s):
                if k2 == "traf":
                    for k3, p3, s3, h3 in boxes(f, p2 + h2, p2 + s2):
                        if k3 == "tfhd":
                            f.seek(p3 + h3)
                            if int.from_bytes(f.read(4), "big") & 1:
                                raise ValueError("base-data-offset absolu non géré")
                        elif k3 == "tfdt":
                            f.seek(p3 + h3)
                            ver = f.read(1)[0]
                            f.seek(p3 + h3 + 4)
                            t = int.from_bytes(f.read(8 if ver == 1 else 4), "big")
            mdat = top[i + 1] if i + 1 < len(top) and top[i + 1][0] == "mdat" else None
            frags.append((t / timescale, p, s, mdat))
        if tid == 1:
            fp, fs, _ = get["ftyp"]
            f.seek(fp)
            ftyp = f.read(fs)
            vp, vs, _ = moov["mvhd"]
            f.seek(vp)
            mvhd = bytearray(f.read(vs))
            mvhd[-4:] = (3).to_bytes(4, "big")  # next_track_ID
        tracks.append({"f": f, "tid": tid, "trak": bytes(trak), "trex": trex, "frags": frags})

    mvex = b"".join(bytes(t["trex"]) for t in tracks if t["trex"])
    moov = mp4_box("moov", bytes(mvhd) + b"".join(t["trak"] for t in tracks)
                   + (mp4_box("mvex", mvex) if mvex else b""))
    order = sorted((fr[0], t["tid"], fr, t) for t in tracks for fr in t["frags"])
    with open(dest + ".part", "wb") as out:
        out.write(ftyp + moov)
        for seq, (_, tid, (_, p, s, mdat), t) in enumerate(order, 1):
            f = t["f"]
            f.seek(p)
            moof = bytearray(f.read(s))
            # mfhd (numéro de fragment) et tfhd (piste) à renuméroter
            for k, bp, bs, bh in boxes(f, p + 8, p + s):
                if k == "mfhd":
                    moof[bp - p + bh + 4:bp - p + bh + 8] = seq.to_bytes(4, "big")
                elif k == "traf":
                    for k2, p2, s2, h2 in boxes(f, bp + bh, bp + bs):
                        if k2 == "tfhd":
                            moof[p2 - p + h2 + 4:p2 - p + h2 + 8] = tid.to_bytes(4, "big")
            out.write(moof)
            if mdat:
                f.seek(mdat[1])
                left = mdat[2]
                while left > 0:
                    chunk = f.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    out.write(chunk)
                    left -= len(chunk)
    for t in tracks:
        t["f"].close()
    os.rename(dest + ".part", dest)


def prepare_trailer(jf, trailer, dest):
    if "youtube" in trailer:
        return prepare_youtube(trailer["youtube"], dest)
    # Transcodage H.264/AAC en MP4 fragmenté : lisible même tronqué, et par le lecteur de l'accueil.
    jf.download("/Videos/%s/stream.mp4" % trailer["Id"], dest, TRAILER_MAX,
                VideoCodec="h264", AudioCodec="aac", MaxWidth=854, MaxHeight=480,
                VideoBitrate=1500000, AudioBitrate=160000, AudioChannels=2)


def prepare_image(jf, it, dest):
    bid, btag = backdrop_ref(it)
    lid, ltag = logo_ref(it)
    pid, ptag = poster_ref(it)
    poster = png_decode(jf.fetch_bytes("/Items/%s/Images/Primary" % pid, tag=ptag, format="png",
                                       maxHeight=AD_H)) if pid else None
    pw = poster[0] if poster else 0
    backdrop = png_decode(jf.fetch_bytes("/Items/%s/Images/Backdrop/0" % bid, tag=btag, format="png",
                                         fillWidth=AD_W - pw, fillHeight=AD_H)) if bid else None
    logo = png_decode(jf.fetch_bytes("/Items/%s/Images/Logo" % lid, tag=ltag, format="png",
                                     maxWidth=AD_W - AD_SPLIT - 112, maxHeight=LOGO_H)) if lid else None
    data = compose_image(backdrop, logo, *headline(it), poster=poster)
    with open(dest + ".part", "wb") as f:
        f.write(data)
    os.rename(dest + ".part", dest)


def headline(it):
    """(titre, sous-titre) d'un élément pour le carrousel."""
    if it.get("Type") == "Episode":
        return it.get("SeriesName") or it.get("Name", ""), "S%dE%d · %s" % (
            it.get("ParentIndexNumber") or 0, it.get("IndexNumber") or 0, it.get("Name", ""))
    return it.get("Name", ""), None


def ad_assets(cfg, jf, items, opts):
    """Actifs du carrousel et correspondance identifiant d'actif → élément Jellyfin.
    Sans bande-annonce prête, un élément est une simple image."""
    os.makedirs(AD_DIR, exist_ok=True)
    section = text(cfg, opts["topSource"], suffix=False)
    assets, keep, seq, seen, fallback = [], {"map.json", "carousel.json"}, 0, set(), []
    # Identifiant d'actif propre à chaque (élément, visuel) et jamais réattribué :
    # l'accueil peut encore afficher une réponse précédente quand on clique.
    amap = read_json(AD_MAP, {})
    if not isinstance(amap.get("ids"), dict):
        amap = {"next": 1, "keys": {}, "ids": {}}

    def asset_id(item_id, kind, key):
        k = "%s|%s|%s" % (item_id, kind, key)
        if k not in amap["keys"]:
            amap["keys"][k] = AD_ID + amap["next"]
            amap["ids"][str(AD_ID + amap["next"])] = item_id
            amap["next"] = amap["next"] % 999999 + 1
        return amap["keys"][k]
    for it in items:
        if it["Id"] in seen or len(seen) >= AD_ITEMS:
            continue
        bid, btag = backdrop_ref(it)
        if not bid:
            continue
        seen.add(it["Id"])
        image = {"parentId": -1, "type": "image", "rotationTime": 6,
                 "sponsoredText": section, "duration": 0,
                 "contentData": jf.base + "/Items/%s/Images/Backdrop/0?%s" % (bid, urllib.parse.urlencode(
                     {"tag": btag, "fillWidth": 1920, "fillHeight": 1920 * AD_H // AD_W, "quality": 90})),
                 "isCached": False, "mime": "image/jpeg"}
        trailer = None
        if opts["adTrailers"]:
            try:
                trailer = trailer_of(jf, it)
            except Exception as e:
                log("bande-annonce %s : %s" % (it["Id"], e))
        key = hashlib.sha1(json.dumps([it["Id"], btag, logo_ref(it)[1], poster_ref(it)[1], headline(it),
                                       CROP_Y, POSTER_WIDEN, "affiche-v5"]).encode()).hexdigest()[:16]

        def prepared(fname, job):
            """Chemin du fichier s'il est prêt ; sinon le met en préparation."""
            keep.add(fname)
            path = os.path.join(AD_DIR, fname)
            if os.path.exists(path):
                return path
            if PREPARER:
                PREPARER.want(fname, lambda: job(path))
            elif fname.endswith(".png") and time.time() < SYNC_UNTIL:
                try:
                    job(path)
                    return path
                except Exception as e:
                    log("carrousel : %s : %s" % (fname, e))
            return None

        # Visuel composé ; tant qu'il n'est pas prêt, l'élément attend hors du carrousel
        full = prepared("full-%s.png" % key, lambda p, i=it: prepare_image(jf, i, p))
        vfile = trailer and trailer_file(trailer)
        if vfile and vfile.startswith("trailer-yt-"):
            keep.add(vfile[:-4] + ".json")  # durée
        vpath = trailer and prepared(vfile,
                                     lambda p, t=trailer: prepare_trailer(jf, t, p))
        if not full:
            fallback.append((it["Id"], image))
            continue
        seq += 1
        image.update(sequenceId=seq, contentData=AD_URL + os.path.basename(full), mime="image/png")
        if trailer:
            if vpath:
                vid = asset_id(it["Id"], "video", vpath)
                assets.append({"id": vid, "parentId": -1, "type": "video", "sequenceId": seq,
                               "rotationTime": 2, "width": 1920, "height": 1080,
                               "sponsoredText": "%s · %s" % (text(cfg, "trailer", suffix=False), section),
                               "contentData": AD_URL + os.path.basename(vpath), "isCached": False,
                               "duration": int(min(trailer_seconds(trailer, vpath), TRAILER_SECONDS)),
                               "mime": "video/mp4", "autoPlay": True})
                image.update(rotationTime=2)
        image["id"] = asset_id(it["Id"], "image", image["contentData"])
        assets.append(image)
    if not assets:  # rien de prêt : les images Jellyfin telles quelles plutôt qu'un carrousel vide
        for item_id, image in fallback:
            seq += 1
            image.update(sequenceId=seq, id=asset_id(item_id, "image", image["contentData"]))
            assets.append(image)
    # Ménage : fichiers d'éléments sortis du carrousel (par le démon seulement,
    # qui sait quels téléchargements sont en cours)
    for f in os.listdir(AD_DIR) if PREPARER else ():
        if f not in keep and not any(f.startswith(k) for k in PREPARER.pending):
            try:
                os.remove(os.path.join(AD_DIR, f))
            except OSError:
                pass
    for part in ("keys", "ids"):  # on garde les 2000 derniers
        amap[part] = dict(list(amap[part].items())[-2000:])
    write_json(AD_MAP, amap)
    return assets


def ad_response(assets):
    # L'accueil ne recharge les visuels que si contextIndex change : il suit le contenu.
    ctx = zlib.crc32(json.dumps(assets, sort_keys=True).encode()) % 1000000
    return {"contextIndex": AD_ID + ctx, "returnValue": True, "assets": assets}


def launch_jellyfin(item_id):
    """Clic sur un actif du carrousel : l'accueil ne sait rien en faire (le
    gestionnaire de pub ne connaît pas nos actifs) ; on lance Jellyfin nous-mêmes
    puis on lui fait afficher la fiche."""
    # luna-send -n 1 sans terminal rend la main avant d'envoyer (cf. jellyhomectl)
    p = subprocess.Popen(["luna-send", "-i", "luna://com.webos.service.applicationmanager/launch",
                          json.dumps({"id": JELLYFIN_APP})],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    p.kill()
    open_item(item_id, time.time())


def check_adclick(state):
    """Nouveau clic sur un de nos actifs ? (règles onCall requestAssetClickInfo /
    handleClickBanner) → ouvrir l'élément. L'accueil enchaîne les deux appels :
    un même actif n'est traité qu'une fois en quelques secondes."""
    try:
        m = os.path.getmtime(ADCLICK)
    except OSError:
        state.setdefault("mtime", None)  # pas encore de clic : le premier comptera
        return
    if m == state.get("mtime"):
        return
    first = "mtime" not in state
    state["mtime"] = m
    d = read_json(ADCLICK, {})
    asset = str((d.get("payload") or {}).get("assetId", ""))
    item_id = ((read_json(AD_MAP, {}) or {}).get("ids") or {}).get(asset)
    now = time.time()
    if first or not item_id or now - d.get("time", 0) > 30:
        return
    if state.get("last") == item_id and now - state.get("at", 0) < 5:
        return
    state.update(last=item_id, at=now)
    log("carrousel : clic sur", item_id)
    threading.Thread(target=launch_jellyfin, args=(item_id,), daemon=True).start()


# ---------------------------------------------------------------- règles

def shelf_entry(shelf_id, rank, url):
    """Rangée ajoutée à la config de l'accueil : l'accueil la demandera au
    serveur LG (qui répondra 404) et la règle associée répondra à sa place."""
    return {"shelfId": shelf_id, "shelfRank": rank, "UIType": "COMMON",
            "isRecommendShelf": "Y",
            "shelfData": {"provider": "SDP", "parameter": {
                "serviceName": "sdp_home", "url": url, "methodType": "REQ_SSL_GET_METHOD"}}}


def covers(cat):
    return {"resume", "latest", "mix"} if cat == "mix" else {cat}


def shown_above(opts):
    """Catégories déjà présentes dans les zones fixes ou sous le bandeau : leur
    rangée dédiée ferait doublon."""
    return covers(opts["topSource"]) | covers(opts["heroSource"]) | covers(opts["underRow"])


def under_source(opts):
    """La rangée sous le bandeau ne répète pas ce que montrent déjà les zones fixes."""
    u = opts["underRow"]
    fixed = covers(opts["heroSource"]) | covers(opts["topSource"])
    return "none" if u in CATEGORIES and covers(u) & fixed else u


def build_rules(opts, files, ad=False):
    """files : {rôle: fichier} des données disponibles ("hero", "under", "resume"…) ;
    ad : le carrousel du haut a des actifs Jellyfin (AD_FILE)."""
    rules, rows, rank = [], [], 3
    top_jf = opts["topSource"] in CATEGORIES and "top" in files
    if top_jf:
        rules.append({"uri": SDX, "request": '"url":"editorsPick"',
                      "save": "lg-top.json", "file": files["top"]})
    hero_jf = opts["heroSource"] in CATEGORIES and "hero" in files
    if hero_jf:
        # Bandeau du haut = étagère RECOMMENDED. La réponse LG d'origine est gardée
        # pour pouvoir la resservir en rangée.
        rules.append({"uri": SDX, "request": "shelfId=HOME_SH_RECOMMENDED",
                      "save": "lg-live.json", "file": files["hero"]})

    under = under_source(opts)
    if under == "lg" and hero_jf:
        rows.append(shelf_entry("HOME_SH_JELLYHOME_UNDER", rank, "jellyhome/under"))
        rules.append({"uri": SDX, "request": '"url":"jellyhome/under"', "file": "lg-live.json",
                      "json": [RESP], "remove": [RESP + "/focusAutoLaunch"]})
    elif under in CATEGORIES and "under" in files:
        rows.append(shelf_entry("HOME_SH_JELLYHOME_UNDER", rank, "jellyhome/under"))
        rules.append({"uri": SDX, "request": '"url":"jellyhome/under"', "file": files["under"]})

    above = shown_above(opts)
    for key in ("resume", "nextUp", "latest"):
        if opts[key] and key in files and key not in above:
            url = "jellyhome/" + key.lower()
            rows.append(shelf_entry("HOME_SH_JELLYHOME_" + key.upper(), rank, url))
            rules.append({"uri": SDX, "request": '"url":"%s"' % url, "file": files[key]})

    if top_jf and opts["topLgRow"] and "lgtop" in files:
        rows.append(shelf_entry("HOME_SH_JELLYHOME_LGTOP", rank, "jellyhome/lgtop"))
        rules.append({"uri": SDX, "request": '"url":"jellyhome/lgtop"', "file": files["lgtop"]})

    cfg_rule = {"uri": SDX, "request": '"url":"getConfig"', "json": [RESP]}
    if rows:
        # Rangées insérées au rang de l'étagère RECOMMENDED : juste sous le bandeau.
        cfg_rule["set"] = {RESP + "/ai_home_info/-%d" % i: r for i, r in enumerate(rows)}
    if opts["hideAds"]:
        # LG intercale des pubs dans le bandeau (adSlotData) et a une rangée pub.
        cfg_rule["remove"] = [RESP + "/ai_home_info/[shelfId=HOME_SH_RECOMMENDED]/adSlotData",
                              RESP + "/ai_home_info/[shelfId=HOME_SH_INLINEADBANNER]"]
    if len(cfg_rule) > 3:
        rules.insert(0, cfg_rule)
    # Un clic sur une carte Jellyfin lance l'app avec l'id de l'élément, qu'elle
    # ignore : on note le lancement pour lui faire afficher la fiche (open_item).
    for uri in ("luna://com.webos.service.applicationmanager/launch",
                "luna://com.webos.applicationManager/launch"):
        rules.append({"uri": uri, "request": JELLYFIN_APP, "onCall": "launch.json"})
    if opts["hideAds"]:
        # Le gestionnaire de pub répond comme quand les pubs sont coupées dans les
        # réglages LG : l'accueil n'affiche alors aucun bloc sponsorisé.
        for scheme in ("luna://", "palm://"):
            rules.append({"uri": scheme + ADMANAGER, "replace": NO_AD})
    # Carrousel du haut (« Zone du haut ») : ces règles passent après la précédente.
    for scheme in ("luna://", "palm://") if ad else ():
        rules.append({"uri": scheme + ADMANAGER, "request": AD_SLOT, "file": AD_FILE})
        # Clic sur un de nos actifs : l'accueil interroge le gestionnaire de pub.
        for method in ("requestAssetClickInfo", "handleClickBanner") if ad else ():
            rules.append({"uri": scheme + ADMANAGER_BASE + method,
                          "request": str(AD_ID // 1000000), "onCall": "adclick.json"})
    user = read_json(USER_RULES, {})
    rules += user.get("rules", []) if isinstance(user, dict) else []
    return {"log": bool(isinstance(user, dict) and user.get("log")), "rules": rules}


def refresh():
    cfg = read_json(CONFIG, {})
    opts = options(cfg)
    status = {"time": int(time.time()), "connected": False}
    files, ad = {}, False
    if cfg.get("token") and cfg.get("server") and cfg.get("userId"):
        jf = Jellyfin(cfg)
        status.update(server=jf.base, userName=cfg.get("userName"))
        # Rôle → catégorie, puis une requête par catégorie distincte
        roles = {}
        if opts["topSource"] in CATEGORIES:
            roles["top"] = opts["topSource"]
        if opts["heroSource"] in CATEGORIES:
            roles["hero"] = opts["heroSource"]
        if under_source(opts) in CATEGORIES:
            roles["under"] = under_source(opts)
        above = shown_above(opts)
        for key in ("resume", "nextUp", "latest"):
            if opts[key] and key not in above:
                roles[key] = key
        try:
            got, counts = {}, {}
            for role, cat in roles.items():
                if cat not in got:
                    got[cat] = fetch(jf, cat)
                    counts[cat] = len(got[cat])
                mode = opts["episodeImages"].get(role, "series")
                # Pas dans le bandeau : il n'affiche pas ces « programmes » sans chaîne
                prog = opts["progress"] and cat in ("resume", "mix") and role not in ("top", "hero")
                if role in ("top", "hero"):
                    items = cards(jf, got[cat], 960, 540, 15, mode, prog)
                else:
                    items = cards(jf, got[cat], 460, 259, 20, mode, prog)
                if items:
                    fname = role + ".json"
                    wrap = editors_pick if role == "top" else shelf
                    write_json(os.path.join(DATA, fname), wrap(text(cfg, cat), items))
                    files[role] = fname
            cat = opts["topSource"]
            if cat in CATEGORIES:
                if cat not in got:
                    got[cat] = fetch(jf, cat)
                    counts[cat] = len(got[cat])
                assets = ad_assets(cfg, jf, got[cat], opts)
                if assets:
                    write_json(os.path.join(DATA, AD_FILE), ad_response(assets))
                    ad = True
                status["adTrailers"] = sum(a["type"] == "video" for a in assets)
            status.update(connected=True, counts=counts)
        except Exception as e:
            status["error"] = str(e)
            log("erreur Jellyfin :", e)
    if lg_top_row():
        files["lgtop"] = "lgtop-row.json"
    write_json(os.path.join(DATA, "rules.json"), build_rules(opts, files, ad))
    write_json(STATUS, status)
    log("rafraîchi :", json.dumps(status, ensure_ascii=False))


# ------------------------------------------------- ouverture de la fiche

def local_ip(host):
    """Adresse de la TV vue par le serveur Jellyfin."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 9))
        return s.getsockname()[0]
    finally:
        s.close()


def open_item(item_id, launched_at):
    """Attend que l'app Jellyfin de la TV soit connectée au serveur, puis lui
    demande d'afficher la fiche (commande « Viewing » du contrôle à distance)."""
    cfg = read_json(CONFIG, {})
    if not cfg.get("token"):
        return
    jf = Jellyfin(cfg)
    try:
        item = jf.get("/Users/%s/Items/%s" % (jf.user, item_id))
        tv = local_ip(urllib.parse.urlparse(jf.base).hostname)
    except Exception as e:
        log("fiche %s : %s" % (item_id, e))
        return
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            sessions = jf.get("/Sessions", ControllableByUserId=jf.user, ActiveWithinSeconds=600)
        except Exception as e:
            log("sessions :", e)
            sessions = []
        mine = cfg.get("deviceId")
        cands = [x for x in sessions
                 if x.get("DeviceId") != mine and x.get("SupportsRemoteControl")
                 and (x.get("RemoteEndPoint") or "").split(":")[0] in (tv, "::ffff:" + tv)]
        if cands:
            sess = max(cands, key=lambda x: x.get("LastActivityDate") or "")
            time.sleep(2)  # laisser l'interface finir de se charger
            try:
                jf.post("/Sessions/%s/Viewing" % sess["Id"], itemType=item.get("Type", ""),
                        itemId=item_id, itemName=item.get("Name", ""))
                log("fiche ouverte : %s (%s)" % (item.get("Name"), sess.get("DeviceName")))
            except Exception as e:
                log("fiche %s : %s" % (item_id, e))
            return
        time.sleep(1)
    log("fiche %s : app Jellyfin introuvable dans les sessions" % item_id)


def check_launch(seen):
    """Nouveau lancement de Jellyfin depuis l'accueil ? → ouvrir la fiche."""
    try:
        m = os.path.getmtime(LAUNCH)
    except OSError:
        return 0 if seen is None else seen  # pas encore de lancement : le premier comptera
    if m == seen:
        return seen
    d = read_json(LAUNCH, {})
    p = d.get("payload") or {}
    item_id = ((p.get("replaceParams") or {}).get("deeplinkingParams") or {}).get("value") \
        or (p.get("params") or {}).get("contentTarget")
    if seen is not None and item_id and len(item_id) == 32 and time.time() - d.get("time", 0) < 30:
        threading.Thread(target=open_item, args=(item_id, d.get("time")), daemon=True).start()
    return m


# ------------------------------------------------------------- commandes

def discover(timeout=2.0):
    """Découverte Jellyfin standard (UDP 7359)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(timeout)
    s.sendto(b"who is JellyfinServer?", ("255.255.255.255", 7359))
    found, end = {}, time.time() + timeout
    while time.time() < end:
        try:
            data, _ = s.recvfrom(4096)
            d = json.loads(data)
            found[d.get("Id")] = {"name": d.get("Name"), "address": d.get("Address")}
        except socket.timeout:
            break
        except ValueError:
            pass
    return list(found.values())


def merge(dst, patch):
    """Fusion récursive ; une valeur null supprime la clé."""
    for k, v in patch.items():
        if v is None:
            dst.pop(k, None)
        elif isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def set_config(b64):
    cfg = merge(read_json(CONFIG, {}), json.loads(base64.b64decode(b64)))
    write_json(CONFIG, cfg, private=True)


def daemon():
    pidfile = os.path.join(DATA, "jellyfeed.pid")
    try:
        old = int(open(pidfile).read())
        # Le numéro peut avoir été réattribué : vérifier que c'est bien nous
        if old != os.getpid() and b"jellyfeed" in open("/proc/%d/cmdline" % old, "rb").read():
            log("déjà lancé (pid %d)" % old)
            return
    except (OSError, ValueError):
        pass
    open(pidfile, "w").write(str(os.getpid()))
    wake = {"now": True}
    signal.signal(signal.SIGUSR1, lambda *_: wake.update(now=True))
    # Une bande-annonce ou une image prête : on la met au carrousel aussitôt.
    global PREPARER
    PREPARER = AdPreparer(on_ready=lambda: wake.update(now=True))
    try:
        serve_ad_files()
    except OSError as e:
        log("carrousel : serveur de fichiers indisponible :", e)
    adclick = {}
    check_adclick(adclick)  # ignore un clic antérieur au démarrage

    def mtimes():
        return tuple(os.path.getmtime(p) if os.path.exists(p) else 0 for p in (CONFIG, USER_RULES, os.path.join(DATA, "lg-top.json")))

    last, seen, launch_seen = 0, None, None
    launch_seen = check_launch(launch_seen)  # ignore un lancement antérieur au démarrage
    while True:
        launch_seen = check_launch(launch_seen)
        check_adclick(adclick)
        m = mtimes()
        if wake["now"] or m != seen or time.time() - last > REFRESH:
            wake["now"], seen, last = False, m, time.time()
            try:
                refresh()
            except Exception as e:
                log("erreur :", e)
        time.sleep(1)


def main():
    os.makedirs(DATA, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "daemon":
        daemon()
    elif cmd == "once":
        global SYNC_UNTIL
        SYNC_UNTIL = time.time() + 60
        refresh()
    elif cmd == "discover":
        print(json.dumps(discover()))
    elif cmd == "set-config":
        set_config(sys.argv[2])
    elif cmd == "status":
        st = read_json(STATUS, {})
        cfg = read_json(CONFIG, {})
        st.update(server=cfg.get("server"), userName=cfg.get("userName"),
                  hasToken=bool(cfg.get("token")), lang=cfg.get("lang"), options=options(cfg))
        print(json.dumps(st, ensure_ascii=False))
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""网易云音乐曲目/时长核实（非官方 API，仅用于辅助核对，失败则回退手动录入）。
优先使用 v1 接口（/api/v1/album/{id}），被反爬时回退旧接口；均不可用时由搜索结果
提供歌手/专辑名/曲目数量用于"X 首"核对，曲目交手动录入。
"""
import hashlib
import json
import time
import requests
from datetime import datetime

API = "https://music.163.com/api"

# ---- 客户端 eapi：歌手作品分类（演唱 / 作词 / 作曲 / 编曲 / 制作 / 演奏）----
EAPI_HOST = "https://interface.music.163.com"
EAPI_KEY = b"e82ckenh8dichen8"
_EAPI_HEAD = {"os": "pc", "appver": "3.1.19.204510", "requestId": 0,
              "osver": "Microsoft-Windows-11-Home-China-build-22631-64bit"}
_EAPI_UA = ("Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Safari/537.36 Chrome/91.0.4472.164 NeteaseMusicDesktop/3.1.19.204510")

# 与网易云客户端歌曲页分类顺序一致
WORK_TYPES = [("演唱", 1), ("作词", 2), ("作曲", 3), ("编曲", 4), ("制作", 5), ("演奏", 6)]

# AES-128-ECB：优先 pycryptodome，其次 cryptography
try:
    from Crypto.Cipher import AES as _AES

    def _ecb_encrypt(data):
        return _AES.new(EAPI_KEY, _AES.MODE_ECB).encrypt(data)

    def _ecb_decrypt(data):
        return _AES.new(EAPI_KEY, _AES.MODE_ECB).decrypt(data)
except Exception:  # pragma: no cover
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend

    def _ecb_encrypt(data):
        c = Cipher(algorithms.AES(EAPI_KEY), modes.ECB(), backend=default_backend()).encryptor()
        return c.update(data) + c.finalize()

    def _ecb_decrypt(data):
        c = Cipher(algorithms.AES(EAPI_KEY), modes.ECB(), backend=default_backend()).decryptor()
        return c.update(data) + c.finalize()


def _pkcs7_pad(b):
    n = 16 - len(b) % 16
    return b + bytes([n]) * n


def _eapi_params(path, obj):
    """按客户端规则加密请求体：aes-128-ecb({path}-36cd479b6b5-{body}-36cd479b6b5-{md5})。"""
    text = json.dumps(obj, separators=(",", ":"))
    digest = hashlib.md5(f"nobody{path}use{text}md5forencrypt".encode()).hexdigest()
    raw = f"{path}-36cd479b6b5-{text}-36cd479b6b5-{digest}"
    return _ecb_encrypt(_pkcs7_pad(raw.encode())).hex().upper()


def _eapi_call(path, payload):
    """发一个 eapi 请求，返回解密后的 dict。"""
    params = _eapi_params(path, payload)
    cookie = "; ".join(f"{k}={v}" for k, v in _EAPI_HEAD.items())
    r = requests.post(f"{EAPI_HOST}/eapi{path}", data={"params": params},
                      headers={"User-Agent": _EAPI_UA, "Cookie": cookie}, timeout=TIMEOUT)
    plain = _ecb_decrypt(r.content)
    body, _ = json.JSONDecoder().raw_decode(plain.decode("utf-8", "ignore"))
    return body


def artist_works(artist_id, work_type=1, limit=50, offset=0):
    """歌手作品分类列表。work_type: 1演唱 2作词 3作曲 4编曲 5制作 6演奏。

    与网易云客户端歌曲页同一接口（/api/v1/artist/songs），按热门排序，
    数据为网易云真实数据；该分类在网易云没有收录时返回空列表。
    """
    path = "/api/v1/artist/songs"
    payload = {
        "header": _EAPI_HEAD, "e_r": True,
        "id": str(artist_id), "private_cloud": "true",
        "work_type": int(work_type), "order": "hot",
        "offset": int(offset), "limit": int(limit),
    }
    last = None
    for i in range(2):
        try:
            body = _eapi_call(path, payload)
        except Exception as e:
            last = str(e)
            time.sleep(0.8)
            continue
        if isinstance(body, dict) and body.get("code") in (-462, -460, 406):
            # 客户端风控：等一下再试
            last = "网易云风控，稍后重试"
            time.sleep(1.2)
            continue
        role = next((n for n, v in WORK_TYPES if v == int(work_type)), "")
        songs = []
        for s in (body or {}).get("songs") or []:
            ar = " / ".join(a.get("name", "") for a in s.get("ar", []) if isinstance(a, dict))
            al = s.get("al") or {}
            songs.append({
                "id": s.get("id"),
                "name": s.get("name", ""),
                "artists": ar,
                "album": al.get("name", "") if isinstance(al, dict) else "",
                "dur": _fmt_dur(s.get("dt") or 0),
                "pic": (al.get("picUrl") or "") if isinstance(al, dict) else "",
            })
        return {"ok": True, "role": role, "work_type": int(work_type),
                "songs": songs, "total": (body or {}).get("total") or len(songs),
                "more": bool((body or {}).get("more"))}
    return {"ok": False, "error": last or "该分类暂无数据"}


HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120 Safari/537.36"),
    "Referer": "https://music.163.com/",
    "Accept": "application/json",
}
TIMEOUT = 12


def _fmt_dur(ms):
    if not ms:
        return ""
    s = int(ms / 1000)
    return f"{s // 60}:{s % 60:02d}"


def _is_verify(j):
    pay = j.get("data", j) if isinstance(j, dict) else {}
    return ("verifyType" in pay) or ("blockText" in pay) or (j.get("code") in (-1, 301))


def _album_year(al):
    pt = al.get("publishTime") or al.get("paid") or 0
    if pt:
        try:
            return datetime.fromtimestamp(pt / 1000).strftime("%Y")
        except Exception:
            pass
    return ""


def _fmt_date(ms):
    if not ms:
        return ""
    try:
        d = datetime.fromtimestamp(ms / 1000)
        return f"{d.year}-{d.month}-{d.day}"
    except Exception:
        return ""


def search_album(query, limit=8):
    for _ in range(2):
        try:
            r = requests.get(f"{API}/search/get", params={"s": query, "type": 10, "limit": limit, "offset": 0},
                             headers=HEADERS, timeout=TIMEOUT)
            data = r.json()
            albums = data.get("result", {}).get("albums", [])
            if albums:
                break
        except Exception as e:
            albums = [{"error": str(e)}]
    out = []
    for a in albums:
        if "error" in a:
            return [{"error": a["error"]}]
        art = a.get("artist", {})
        art_name = art.get("name", "") if isinstance(art, dict) else str(art)
        out.append({
            "id": a["id"],
            "name": a.get("name", ""),
            "artist": art_name,
            "artist_id": (art or {}).get("id") if isinstance(art, dict) else None,
            "size": a.get("size", 0),
            "date": _fmt_date(a.get("publishTime")),
            "year": _album_year(a),
            "ts": a.get("publishTime") or 0,
            "pic": a.get("picUrl", ""),
        })
    return out


def search_artist(query, limit=12):
    """按歌手名搜索，返回歌手列表（带重试，应对接口偶发限流）。"""
    for _ in range(2):
        try:
            r = requests.get(f"{API}/search/get", params={"s": query, "type": 100, "limit": limit, "offset": 0},
                             headers=HEADERS, timeout=TIMEOUT)
            j = r.json()
            arts = (j.get("result") or {}).get("artists") or []
            out = []
            for a in arts:
                out.append({
                    "id": a.get("id"),
                    "name": a.get("name", ""),
                    "alias": (a.get("alias") or [])[:2],
                    "albumSize": a.get("albumSize", 0),
                    "pic": a.get("picUrl", ""),
                })
            if out:
                return out
        except Exception:
            pass
    return []


def _norm_albums(albums):
    """把 hotAlbums / albums 原始结构统一成统一字典，按发行时间倒序。"""
    out = []
    for a in albums:
        art = a.get("artist", {})
        art_name = art.get("name", "") if isinstance(art, dict) else str(art or "")
        out.append({
            "id": a.get("id"),
            "name": a.get("name", ""),
            "artist": art_name,
            "artist_id": (art or {}).get("id") if isinstance(art, dict) else None,
            "size": a.get("size", 0),
            "date": _fmt_date(a.get("publishTime")),
            "year": _album_year(a),
            "ts": a.get("publishTime") or 0,
            "pic": a.get("picUrl", ""),
        })
    out.sort(key=lambda x: -(x.get("ts") or 0))
    return out


def get_artist_albums(artist_id, artist_name, limit=60):
    """歌手专辑列表：优先直连接口，被反爬时回退为「按歌手名搜专辑 + 按歌手ID过滤」。"""
    try:
        r = requests.get(f"{API}/artist/albums/{artist_id}?limit={limit}&offset=0",
                         headers=HEADERS, timeout=TIMEOUT)
        j = r.json()
        pay = j.get("data", j) if isinstance(j.get("data"), dict) else j
        if not _is_verify(j):
            albums = j.get("hotAlbums") or pay.get("hotAlbums") or j.get("albums") or pay.get("albums") or []
            if albums:
                return _norm_albums(albums)
    except Exception:
        pass
    cands = search_album(artist_name or "", limit=limit)
    out, seen = [], set()
    for a in cands:
        if a.get("error"):
            continue
        aid = a.get("artist_id")
        match = (aid is not None and int(aid) == int(artist_id)) or (aid is None and a.get("artist") == artist_name)
        if match and a.get("id") not in seen:
            seen.add(a["id"])
            out.append(a)
    out.sort(key=lambda x: -(x.get("ts") or 0))
    return out


def get_artist_detail(artist_id):
    """歌手主页数据：简介 + 热门歌曲（带重试，应对接口偶发限流）。"""
    for _ in range(2):
        try:
            r = requests.get(f"{API}/v1/artist/{artist_id}", headers=HEADERS, timeout=TIMEOUT)
            j = r.json()
            if _is_verify(j):
                continue
            art = j.get("artist") or {}
            songs = []
            for s in j.get("hotSongs") or []:
                ar = " / ".join(a.get("name", "") for a in s.get("ar", []) if isinstance(a, dict))
                al = (s.get("al") or {}).get("name", "") if isinstance(s.get("al"), dict) else ""
                songs.append({
                    "name": s.get("name", ""),
                    "artists": ar,
                    "album": al,
                    "dur": _fmt_dur(s.get("dt") or 0),
                    "pic": ((s.get("al") or {}).get("picUrl") or "") if isinstance(s.get("al"), dict) else "",
                })
            alias = art.get("alias") or []
            return {
                "ok": bool(art),
                "name": art.get("name", ""),
                "alias": alias[0] if alias else (art.get("trans") or ""),
                "brief": (art.get("briefDesc") or "").strip(),
                "songs": songs,
                "musicSize": art.get("musicSize", 0),
                "albumSize": art.get("albumSize", 0),
                "mvSize": art.get("mvSize", 0),
                "pic": art.get("picUrl") or art.get("img1v1Url") or "",
            }
        except Exception:
            continue
    return {"ok": False, "error": "歌手信息接口被限流，稍后重试"}


def fetch_cover(url, size=1400):
    """下载专辑封面（网易云图床需带 Referer），返回 PIL Image 或 None。"""
    if not url:
        return None
    try:
        u = f"{url}?param={size}y{size}" if "?" not in url else url
        r = requests.get(u, headers={"User-Agent": HEADERS["User-Agent"], "Referer": "https://music.163.com/"},
                         timeout=20)
        from PIL import Image
        import io as _io
        return Image.open(_io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def get_album(album_id):
    """拉取专辑详情：曲目名、时长、歌手、发行年。多接口回退。"""
    urls = [
        f"{API}/v1/album/{album_id}?total=true",
        f"{API}/album/{album_id}",
    ]
    # 网易云反爬是瞬时性的，做多轮重试（每轮依次尝试各接口）
    for attempt in range(3):
        if attempt:
            time.sleep(0.8)
        for url in urls:
            try:
                r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
                j = r.json()
            except Exception:
                continue
            if _is_verify(j):
                continue
            pay = j.get("data", j) if isinstance(j.get("data"), dict) else j
            songs = pay.get("songs", []) or j.get("songs", [])
            al = pay.get("album", {}) or j.get("album", {})
            if not isinstance(songs, list) or not songs:
                continue
            main_artist = ""
            if isinstance(al.get("artist"), dict):
                main_artist = al.get("artist", {}).get("name", "")
            elif isinstance(al.get("artist"), str):
                main_artist = al["artist"]
            year = _album_year(al)
            tracks = []
            for i, s in enumerate(songs, 1):
                artists = [a.get("name", "") for a in s.get("ar", []) if isinstance(a, dict)]
                feat = ""
                others = [x for x in artists if x and x != main_artist]
                if others:
                    feat = f"(feat. {' & '.join(others)})"
                tracks.append({
                    "num": f"{i:02d}",
                    "title": s.get("name", ""),
                    "sub": feat or None,
                    "dur": _fmt_dur(s.get("dt") or s.get("duration", 0)),
                })
            return {
                "ok": True,
                "artist": main_artist,
                "album": al.get("name", ""),
                "year": year,
                "date": _fmt_date(al.get("publishTime")) or year,
                "size": al.get("size", len(tracks)),
                "tracks": tracks,
                "pic": al.get("picUrl", ""),
            }
    return {"ok": False, "error": "网易云详情接口被反爬拦截，曲目请手动录入"}


def fetch(query):
    """一步到位：搜索首个候选专辑并返回详情；详情不可用时保留搜索到的歌手/专辑/数量。"""
    cands = search_album(query, limit=5)
    if not cands or "error" in cands[0]:
        return {"ok": False, "candidates": cands, "error": cands[0].get("error", "无结果") if cands else "无结果"}
    best = cands[0]
    detail = get_album(best["id"])
    detail["candidates"] = cands
    if detail.get("ok"):
        detail["size"] = best.get("size") or detail.get("size")
        if not detail.get("year") and best.get("year"):
            detail["year"] = best["year"]
        if not detail.get("pic") and best.get("pic"):
            detail["pic"] = best["pic"]
        return detail
    # 详情被拦截：仍用搜索结果提供基础信息与曲目数量
    return {
        "ok": True,
        "artist": best.get("artist", ""),
        "album": best.get("name", ""),
        "year": best.get("year", ""),
        "size": best.get("size", 0),
        "pic": best.get("pic", ""),
        "tracks": [],
        "tracks_manual": True,
        "candidates": cands,
        "note": "已核实歌手/专辑与曲目数量，详情接口被反爬拦截，曲目请手动补全",
    }


if __name__ == "__main__":
    import sys
    res = fetch(sys.argv[1] if len(sys.argv) > 1 else "Übermensch G-DRAGON")
    print(res)

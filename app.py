# -*- coding: utf-8 -*-
"""拾音乐坊 —— 本地 Web 服务。"""
import os, io, json, time, uuid, shutil, re
import requests
from PIL import Image
from flask import Flask, request, jsonify, send_file, send_from_directory, Response

from core import palette as pal
from core import generator as gen
from core import netease as ne
from core import keychain as kc

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
HISTORY = os.path.join(DATA, "history.json")
TRASH = os.path.join(DATA, ".trash")              # 删除记录的回收站（可恢复）
TRASH_INDEX = os.path.join(TRASH, "index.json")
os.makedirs(DATA, exist_ok=True)
os.makedirs(TRASH, exist_ok=True)
if not os.path.exists(HISTORY):
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32MB


def load_history():
    with open(HISTORY, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(h):
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=2)


# ---------------- 制作记录删除（软删除 + 可回滚） ----------------
_ID_RE = re.compile(r"^[0-9a-fA-F]{6,32}$")   # 只允许生成时用的 hex id，防路径穿越


def _trash_index():
    if not os.path.exists(TRASH_INDEX):
        return {}
    try:
        with open(TRASH_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_trash_index(idx):
    with open(TRASH_INDEX, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)


def _dir_size(path):
    """统计目录内所有文件字节数，用于展示释放的空间。"""
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def trash_records(ids, purge=False):
    """把制作记录移出列表；成品目录默认移到 data/.trash/ 可恢复，purge=True 才彻底删除。
    返回 (deleted, skipped)。只接受合法 hex id 且必须存在于当前历史中。"""
    h = load_history()
    idx = _trash_index()
    deleted, skipped = [], []
    for rid in ids:
        if not isinstance(rid, str) or not _ID_RE.match(rid) or rid not in h:
            skipped.append(rid)
            continue
        rec = h.pop(rid)
        src = os.path.join(DATA, rid)
        if purge:
            shutil.rmtree(src, ignore_errors=True)
        else:
            folder = rid
            dst = os.path.join(TRASH, folder)
            if os.path.exists(dst):                       # 同名时加时间戳，绝不覆盖
                folder = rid + "_" + str(int(time.time()))
                dst = os.path.join(TRASH, folder)
            if os.path.isdir(src):
                shutil.move(src, dst)
            idx[rid] = {"record": rec, "folder": folder,
                        "deleted_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        deleted.append(rid)
    if deleted:
        save_history(h)
        if not purge:
            _save_trash_index(idx)
    return deleted, skipped


@app.route("/")
def index():
    return send_from_directory(os.path.join(BASE, "templates"), "index.html")


@app.route("/api/palette", methods=["POST"])
def api_palette():
    cover_file = request.files.get("cover")
    if cover_file is None:
        return jsonify({"ok": False, "error": "缺少封面图"})
    cover = Image.open(io.BytesIO(cover_file.read())).convert("RGB")
    p = pal.extract_palette(cover)
    return jsonify({"ok": True, "swatches": pal.swatches(p), "palette": p})


@app.route("/api/netease", methods=["POST"])
def api_netease():
    """按关键词搜专辑候选。"""
    q = (request.json or {}).get("query", "")
    if not q:
        return jsonify({"ok": False, "error": "缺少查询词"})
    res = ne.fetch(q)
    res["source"] = "ne"
    return jsonify(res)


@app.route("/api/netease/album", methods=["POST"])
def api_netease_album():
    """专辑详情（曲目）。"""
    aid = (request.json or {}).get("album_id")
    if not aid:
        return jsonify({"ok": False, "error": "缺少 album_id"})
    return jsonify(ne.get_album(aid))


# ---------- 首页 ----------
HOME_HOT = ["周杰伦", "G-DRAGON", "林俊杰", "陈奕迅", "邓紫棋",
            "泰勒·斯威夫特", "薛之谦", "IU", "Adele", "Bruno Mars"]
_home_cache = {"t": 0, "artists": []}


@app.route("/api/home", methods=["GET"])
def api_home():
    """首页数据：热门歌手（带头像）+ 最近制作。结果缓存 10 分钟。"""
    global _home_cache
    now = time.time()
    if now - _home_cache["t"] > 600 or not _home_cache["artists"]:
        artists = []

        def _one(name):
            try:
                res = ne.search_artist(name, limit=6)
                m = next((a for a in res if a.get("name") == name), None)
                m = m or (res[0] if res else None)
                if m:
                    return {"id": m.get("id"), "name": m.get("name"),
                            "pic": m.get("pic", ""), "alias": m.get("alias", []) or []}
            except Exception:
                return None

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(5) as ex:
            artists = [a for a in ex.map(_one, HOME_HOT) if a]
        _home_cache["t"] = now
        _home_cache["artists"] = artists
    h = load_history()
    recent = sorted(h.values(), key=lambda x: x.get("created", ""), reverse=True)[:6]
    recent = [{
        "id": r["id"], "artist": r.get("artist", ""), "album": r.get("album", ""),
        "created": r.get("created", ""),
        "cover": f"/api/file/{r['id']}/1-封面.png",
    } for r in recent]
    return jsonify({"ok": True, "hot_artists": _home_cache["artists"], "recent": recent})


@app.route("/api/search/artist", methods=["POST"])
def api_search_artist():
    """搜歌手。"""
    q = (request.json or {}).get("query", "")
    if not q:
        return jsonify({"ok": False, "error": "缺少查询词", "artists": []})
    artists = ne.search_artist(q)
    if artists:
        return jsonify({"ok": True, "artists": artists, "source": "ne"})
    return jsonify({"ok": False, "error": "没搜到该歌手", "artists": []})


@app.route("/api/artist/detail", methods=["POST"])
def api_artist_detail():
    """歌手简介 + 热歌。"""
    aid = (request.json or {}).get("artist_id")
    if not aid:
        return jsonify({"ok": False, "error": "缺少 artist_id"})
    return jsonify(ne.get_artist_detail(aid))


@app.route("/api/artist/albums", methods=["POST"])
def api_artist_albums():
    """歌手专辑列表。"""
    d = request.json or {}
    aid, aname = d.get("artist_id"), d.get("artist_name", "")
    if not aid:
        return jsonify({"ok": False, "error": "缺少 artist_id", "albums": []})
    return jsonify({"ok": True, "albums": ne.get_artist_albums(aid, aname),
                    "source": "ne"})


_img_cache = {}   # url -> bytes（带容量上限的简易缓存）
_img_order = []

_works_cache = {}   # (artist_id, work_type) -> (时间戳, 结果)


@app.route("/api/artist/works", methods=["POST"])
def api_artist_works():
    """歌手歌曲页分类作品：演唱 / 作词 / 作曲 / 编曲 / 制作 / 演奏（网易云客户端同源数据）。

    支持分页：传 offset（起始偏移）与 limit（每页数量）；all=true 表示进入「全部 XX」
    全量列表页，统一走作品分类接口（即使演唱也按热度拉全量，而非歌手页 50 首热门）。
    """
    d = request.json or {}
    aid = d.get("artist_id")
    if not aid:
        return jsonify({"ok": False, "error": "缺少 artist_id", "songs": []})
    wt = int(d.get("work_type", 1) or 1)
    limit = int(d.get("limit", 50) or 50)
    offset = int(d.get("offset", 0) or 0)
    all_flag = bool(d.get("all", False))
    # 缓存键带 offset/all，逐页缓存 5 分钟，降低风控概率
    key = (str(aid), wt, limit, offset, all_flag)
    hit = _works_cache.get(key)
    if hit and time.time() - hit[0] < 300:
        return jsonify(hit[1])
    if (not all_flag) and offset == 0 and wt == 1:
        # 「演唱 · 热门50」与网易云客户端歌手页完全一致，取歌手页 hotSongs；
        # 该接口偶发限流时回退到作品分类接口（按热度的全部演唱作品）。
        det = ne.get_artist_detail(aid)
        music_size = det.get("musicSize") or len(det.get("songs", []))
        if det.get("ok") and det.get("songs"):
            res = {"ok": True, "role": "演唱", "work_type": 1,
                   "songs": det["songs"][:limit],
                   "total": music_size,
                   "more": music_size > limit,
                   "source": "hotsongs"}
        else:
            res = ne.artist_works(aid, 1, limit=limit, offset=offset)
    else:
        res = ne.artist_works(aid, wt, limit=limit, offset=offset)
    _works_cache[key] = (time.time(), res)
    return jsonify(res)


KC_DIR = os.path.join(DATA, "_keychain")

# ---- 装扮中心 · 播放器样式（数据源：网易云装扮中心官方 CDN 原图，抓包提取 URL 后下载）----
SKINS_FILE = os.path.join(DATA, "player_skins.json")
SKIN_SEL = os.path.join(DATA, "player_skin_selected.json")


def _skins_data():
    with open(SKINS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _skin_selected():
    try:
        with open(SKIN_SEL, encoding="utf-8") as f:
            return str(json.load(f).get("id") or "")
    except Exception:
        return ""


@app.route("/api/player-skins", methods=["GET"])
def api_player_skins():
    d = _skins_data()
    return jsonify({"ok": True, "panels": d["panels"], "active_panel": d["active_panel"],
                    "categories": d["categories"], "skins": d["skins"],
                    "selected": _skin_selected(), "source": d["source"],
                    "source_short": d.get("source_short", d["source"]),
                    "source_note": d.get("source_note", ""),
                    "captured_at": d["captured_at"]})


@app.route("/api/player-skins/select", methods=["POST"])
def api_player_skins_select():
    sid = str((request.get_json(silent=True) or {}).get("id") or "")
    ids = {s["id"] for s in _skins_data()["skins"]}
    if sid and sid not in ids:
        return jsonify({"ok": False, "error": "样式不存在"}), 400
    with open(SKIN_SEL, "w", encoding="utf-8") as f:
        json.dump({"id": sid, "ts": int(time.time())}, f, ensure_ascii=False)
    return jsonify({"ok": True, "selected": sid})
os.makedirs(KC_DIR, exist_ok=True)


@app.route("/api/keychain", methods=["POST"])
def api_keychain():
    """歌曲制作：按制作页勾选的商品/款式/参数合成钥匙扣商品图、电商白底图、黑胶播放界面与拼版。"""
    d = request.json or {}
    cover_url = (d.get("cover_url") or "").strip()
    song = (d.get("song") or "").strip()[:40]
    artist = (d.get("artist") or "").strip()[:40]
    album = (d.get("album") or "").strip()[:40]
    dur = (d.get("dur") or "").strip()[:10]
    if not cover_url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "缺少有效的封面地址"})
    try:
        r = requests.get(cover_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        cover = Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception as e:
        return jsonify({"ok": False, "error": "封面下载失败: " + str(e)})

    styles = [s for s in (d.get("styles") or ["classic"]) if s in kc.STYLES][:2] or ["classic"]
    outputs = [o for o in (d.get("outputs") or ["scene", "white", "vinyl"])
               if o in ("scene", "white", "vinyl")][:3]
    params = d.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    try:
        items = kc.generate_all(cover, styles, outputs, params,
                                song=song, artist=artist, album=album, dur=dur)
    except Exception as e:
        return jsonify({"ok": False, "error": "合成失败: " + str(e)})

    dpi = max(72, min(1200, int(params.get("dpi") or 1000)))
    rid = uuid.uuid4().hex[:10]
    result, files = [], {}
    for group, label, key, im, transparent in items:
        ext = "png" if transparent else "jpg"
        name = f"{rid}-{key}.{ext}"
        path = os.path.join(KC_DIR, name)
        if transparent:
            im.convert("RGBA").save(path, "PNG")
        else:
            im.convert("RGB").save(path, "JPEG", quality=88, dpi=(dpi, dpi))
        url = "/api/keychain/img/" + name
        files[key] = url
        result.append({"group": group, "label": label, "url": url})
    return jsonify({"ok": True, "id": rid, "song": song, "artist": artist,
                    "styles": styles, "outputs": outputs, "dpi": dpi,
                    "player_skin": str(params.get("player_skin") or ""),
                    "items": result, "files": files})


@app.route("/api/keychain/img/<name>", methods=["GET"])
def api_keychain_img(name):
    if not re.match(r"^[0-9a-f]{10}-[a-z0-9_]+\.(jpg|png)$", name):
        return jsonify({"ok": False, "error": "非法文件名"}), 404
    path = os.path.join(KC_DIR, name)
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "文件不存在"}), 404
    return send_file(path)


@app.route("/api/img", methods=["GET"])
def api_img():
    """代理网易云图片（图床需带 Referer），带缓存与重试，避免前端图片加载失败。"""
    import requests
    from io import BytesIO
    url = request.args.get("url", "")
    size = request.args.get("s", "400")
    if not url:
        return "missing url", 400
    key = f"{url}?s={size}"
    if key in _img_cache:
        return Response(_img_cache[key], mimetype="image/jpeg")
    u = f"{url}?param={size}y{size}" if "?" not in url else url
    last_err = None
    for _ in range(3):
        try:
            r = requests.get(u, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"},
                             timeout=12)
            if r.status_code == 200 and r.content:
                if len(_img_cache) > 400:
                    _img_order and _img_cache.pop(_img_order.pop(0), None)
                _img_cache[key] = r.content
                _img_order.append(key)
                return Response(r.content, mimetype="image/jpeg")
        except Exception as e:
            last_err = e
    return (str(last_err) or "fetch failed"), 502


@app.route("/api/generate_from_album", methods=["POST"])
def api_generate_from_album():
    """从专辑页一键制作：自动下载专辑封面 + 拉取真实曲目，直接生成全套素材。"""
    d = request.json or {}
    album_id = d.get("album_id")
    pic = d.get("pic", "")
    extra = d.get("params", {})
    if not album_id:
        return jsonify({"ok": False, "error": "缺少 album_id"})

    src = "ne"
    rid = album_id
    detail = ne.get_album(rid)
    if not detail.get("ok"):
        return jsonify({"ok": False, "error": detail.get("error", "曲目获取失败")})
    if not detail.get("album") and extra.get("album_name"):
        detail["album"] = extra["album_name"]

    cover_file = request.files.get("cover")
    if cover_file is not None:
        cover = Image.open(io.BytesIO(cover_file.read())).convert("RGB")
    else:
        cover = ne.fetch_cover(pic or detail.get("pic", ""))
    if cover is None:
        return jsonify({"ok": False, "error": "封面获取失败，请手动上传一张封面"})

    p = pal.extract_palette(cover)
    sw = pal.swatches(p)
    params = {
        "artist": detail.get("artist", ""),
        "album": detail.get("album", ""),
        "year": detail.get("year", ""),
        # 厂牌：手动填写为准
        "label": extra.get("label") or "",
        "ean": extra.get("ean", ""),
        "tracks": detail.get("tracks", []),
    }
    params.update({k: v for k, v in extra.items() if v})

    rid = uuid.uuid4().hex[:10]
    out_dir = os.path.join(DATA, rid)
    result = gen.generate(cover, p, params, out_dir, seed=int(time.time()) % 100000)

    h = load_history()
    h[rid] = {
        "id": rid, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "artist": params.get("artist", ""), "album": params.get("album", ""),
        "params": params, "palette": p, "swatches": sw,
        "files": list(result["files"].keys()), "zip": os.path.basename(result["zip"]),
    }
    save_history(h)
    return jsonify({
        "ok": True, "id": rid, "swatches": sw,
        "files": {k: f"/api/file/{rid}/{k}" for k in result["files"]},
        "zip": f"/api/zip/{rid}",
        "overview": f"/api/file/{rid}/★版面总览-1比1.png",
    })


@app.route("/api/generate", methods=["POST"])
def api_generate():
    cover_file = request.files.get("cover")
    params = json.loads(request.form.get("params", "{}"))
    if cover_file is None:
        return jsonify({"ok": False, "error": "缺少封面图"})
    cover = Image.open(io.BytesIO(cover_file.read())).convert("RGB")

    # 取色定调
    p = pal.extract_palette(cover)
    sw = pal.swatches(p)

    rid = uuid.uuid4().hex[:10]
    out_dir = os.path.join(DATA, rid)
    seed = int(time.time()) % 100000
    result = gen.generate(cover, p, params, out_dir, seed=seed)

    rec = {
        "id": rid,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "artist": params.get("artist", ""),
        "album": params.get("album", ""),
        "params": params,
        "palette": p,
        "swatches": sw,
        "files": list(result["files"].keys()),
        "zip": os.path.basename(result["zip"]),
    }
    h = load_history()
    h[rid] = rec
    save_history(h)

    return jsonify({
        "ok": True,
        "id": rid,
        "swatches": sw,
        "files": {k: f"/api/file/{rid}/{k}" for k in result["files"]},
        "zip": f"/api/zip/{rid}",
        "overview": f"/api/file/{rid}/★版面总览-1比1.png",
    })


@app.route("/api/history", methods=["GET"])
def api_history():
    h = load_history()
    items = sorted(h.values(), key=lambda x: x.get("created", ""), reverse=True)
    return jsonify(items)


@app.route("/api/history/delete", methods=["POST"])
def api_history_delete():
    """批量删除制作记录：body {"ids":[...]}，默认移入回收站可恢复。
    可选 "purge": true 表示彻底删除（不可恢复）。"""
    d = request.json or {}
    ids = d.get("ids", [])
    if not isinstance(ids, list) or not ids:
        return jsonify({"ok": False, "error": "请选择要删除的制作记录"})
    if len(ids) > 200:
        return jsonify({"ok": False, "error": "单次最多删除 200 条"})
    purge = bool(d.get("purge"))
    # 删除前统计占用，用于回报实际释放的空间
    before = 0
    for rid in ids:
        p = os.path.join(DATA, str(rid))
        if isinstance(rid, str) and _ID_RE.match(rid) and os.path.isdir(p):
            before += _dir_size(p)
    deleted, skipped = trash_records(ids, purge=purge)
    return jsonify({"ok": True, "deleted": deleted, "skipped": skipped,
                    "count": len(deleted), "purged": purge,
                    "freed_mb": round(before / 1024 / 1024, 2),
                    "trash": os.path.relpath(TRASH, BASE)})


@app.route("/api/history/restore", methods=["POST"])
def api_history_restore():
    """回滚：从回收站恢复记录。body {"ids":[...]}（供误删恢复用）。"""
    d = request.json or {}
    ids = d.get("ids", [])
    if not isinstance(ids, list) or not ids:
        return jsonify({"ok": False, "error": "缺少 ids"})
    idx, h, restored = _trash_index(), load_history(), []
    for rid in ids:
        info = idx.get(rid)
        if not info or rid in h:
            continue
        src = os.path.join(TRASH, info.get("folder") or rid)
        dst = os.path.join(DATA, rid)
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.move(src, dst)
        h[rid] = info["record"]
        idx.pop(rid, None)
        restored.append(rid)
    if restored:
        save_history(h)
        _save_trash_index(idx)
    return jsonify({"ok": True, "restored": restored, "count": len(restored)})


@app.route("/api/trash/info", methods=["GET"])
def api_trash_info():
    """回收站占用情况，供前端展示「清空回收站」入口。"""
    idx = _trash_index()
    items = [{"id": rid,
              "artist": (info.get("record") or {}).get("artist", ""),
              "album": (info.get("record") or {}).get("album", ""),
              "deleted_at": info.get("deleted_at", "")}
             for rid, info in idx.items()]
    return jsonify({"ok": True, "count": len(idx), "items": items,
                    "mb": round(_dir_size(TRASH) / 1024 / 1024, 2)})


@app.route("/api/trash/empty", methods=["POST"])
def api_trash_empty():
    """彻底清空回收站并释放磁盘空间（不可恢复）。只清理 TRASH 下的子目录。"""
    idx = _trash_index()
    freed, folders = 0, 0
    for name in os.listdir(TRASH):
        p = os.path.join(TRASH, name)
        if os.path.isdir(p):
            freed += _dir_size(p)
            shutil.rmtree(p, ignore_errors=True)
            folders += 1
    _save_trash_index({})
    return jsonify({"ok": True, "removed": len(idx), "folders": folders,
                    "freed_mb": round(freed / 1024 / 1024, 2)})


@app.route("/api/history/<rid>", methods=["GET"])
def api_history_item(rid):
    h = load_history()
    rec = h.get(rid)
    if not rec:
        return jsonify({"ok": False, "error": "未找到记录"})
    return jsonify({
        "ok": True,
        "record": rec,
        "files": {k: f"/api/file/{rid}/{k}" for k in rec["files"]},
        "zip": f"/api/zip/{rid}",
    })


@app.route("/api/file/<rid>/<path:name>", methods=["GET"])
def api_file(rid, name):
    path = os.path.join(DATA, rid, name)
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "文件不存在"}), 404
    return send_file(path)


@app.route("/api/zip/<rid>", methods=["GET"])
def api_zip(rid):
    path = os.path.join(DATA, rid, load_history().get(rid, {}).get("zip", ""))
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "压缩包不存在"}), 404
    return send_file(path, as_attachment=True)


@app.route("/api/delete/<rid>", methods=["DELETE"])
def api_delete(rid):
    """单条删除（兼容旧调用），统一走回收站软删除。"""
    deleted, skipped = trash_records([rid])
    return jsonify({"ok": bool(deleted), "deleted": deleted, "skipped": skipped})
    return jsonify({"ok": False, "error": "未找到"})


if __name__ == "__main__":
    import os as _os
    port = int(_os.environ.get("PORT", 8011))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

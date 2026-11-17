#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""网易云登录态获取 + 装扮中心（播放器样式）真实接口探测。

安全约定：
  - 只用扫码授权，不接收、不存储账号密码。
  - 登录态 Cookie 只写 data/netease_session.json，chmod 600，
    不放 static/、不进 history、不提交仓库、不写进部署包。
  - 该 Cookie 等同于账号凭证，仅用于本机调试抓取。

用法：
  python3.11 tools/netease_dress.py key          # 生成新 key + 二维码
  python3.11 tools/netease_dress.py watch <key>  # 轮询扫码状态，成功后落登录态
  python3.11 tools/netease_dress.py probe        # 用登录态撞装扮接口，输出抓到的样式
"""
import os
import sys
import json
import time
import base64
import random
import string
import requests

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SESSION = os.path.join(DATA, "netease_session.json")
QR_PNG = os.path.join(os.path.dirname(ROOT), "拾音乐坊-网易云扫码登录.png")
KEY_TXT = os.path.join(DATA, "netease_login_key.txt")
PROBE_OUT = os.path.join(DATA, "dress_probe.json")

NONCE = b"0CoJUm6Qyw8W8jud"
IV = b"0102030405060708"
PUB = "010001"
MOD = ("00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152"
       "b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda9"
       "2557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe48"
       "75d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")


def _aes(t, k):
    return base64.b64encode(AES.new(k, AES.MODE_CBC, IV).encrypt(pad(t.encode(), 16))).decode()


def _rsa(s):
    rev = s[::-1].encode().hex()
    return format(pow(int(rev, 16), int(PUB, 16), int(MOD, 16)), "x").zfill(256)


def weapi(obj):
    t = json.dumps(obj, separators=(",", ":"))
    sk = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
    return {"params": _aes(_aes(t, NONCE), sk.encode()), "encSecKey": _rsa(sk)}


def sess(cookie=""):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://music.163.com/",
                      "Content-Type": "application/x-www-form-urlencoded"})
    if cookie:
        s.headers["Cookie"] = cookie
    return s


def cmd_key():
    os.makedirs(DATA, exist_ok=True)
    r = sess().post("https://music.163.com/weapi/login/qrcode/unikey",
                    data=weapi({"type": 1, "csrf_token": ""}), timeout=10)
    key = r.json().get("unikey")
    if not key:
        print("NOKEY", r.text[:200]); return
    open(KEY_TXT, "w").write(key)
    url = "https://music.163.com/login?codekey=" + key
    import qrcode
    # 纯二维码、不加任何文字或装饰，保证手机相机可直接识别
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=14, border=4)
    q.add_data(url); q.make(fit=True)
    im = q.make_image(fill_color="black", back_color="white").convert("RGB")
    im.save(QR_PNG)
    print("KEY", key)
    print("QR", QR_PNG)
    print("URL", url)


def cmd_watch(key, seconds=600):
    """轮询扫码状态；801 待扫 / 802 已扫待确认 / 803 授权成功 / 800 过期。"""
    s = sess()
    end = time.time() + seconds
    last = None
    while time.time() < end:
        try:
            r = s.post("https://music.163.com/weapi/login/qrcode/client/login",
                       data=weapi({"key": key, "type": 1, "csrf_token": ""}), timeout=10)
            j = r.json()
            code = j.get("code")
            if code != last:
                print(time.strftime("%H:%M:%S"), "code", code, j.get("message", ""), flush=True)
                if code == 802:
                    print(">>> 已扫码，请在手机 App 上点「确认登录」<<<", flush=True)
                last = code
            if code == 803:
                cookies = s.cookies.get_dict()
                # 响应 Set-Cookie 里通常含 MUSIC_U / __csrf / NMTID
                setc = r.headers.get("Set-Cookie", "")
                payload = {"cookies": cookies, "set_cookie": setc,
                           "raw": r.text[:400], "ts": int(time.time())}
                os.makedirs(DATA, exist_ok=True)
                with open(SESSION, "w") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                os.chmod(SESSION, 0o600)
                print("SAVED", SESSION, "cookies", list(cookies.keys()), flush=True)
                # 立刻探测（含登录态 eapi）
                cmd_probe()
                return
            if code == 800:  # 二维码过期
                print("EXPIRED", flush=True); return
        except Exception as e:
            print("ERR", type(e).__name__, str(e)[:60], flush=True)
        time.sleep(2)
    print("TIMEOUT", flush=True)


# 装扮中心 / 播放器样式 可能的私有路径（带登录态逐个试）
DRESS_PATHS = [
    "/weapi/dress/center/homepage", "/weapi/dress/player/style/list",
    "/weapi/v1/dress/player/style/list", "/weapi/dress/style/list",
    "/weapi/dress/list", "/weapi/dress/mall/home", "/weapi/dressup/home",
    "/weapi/player/style/list", "/weapi/v1/player/style/list",
    "/weapi/playsquare/style/list", "/weapi/dress/product/list",
    "/weapi/dress/category/list", "/weapi/dress/config/get",
    "/weapi/content/dress/style/list", "/weapi/middle/dress/style/list",
    "/api/dress/center/homepage", "/api/dress/player/style/list",
    "/api/v1/dress/player/style/list", "/api/dress/style/list",
    "/api/dress/list", "/api/dress/mall/home", "/api/dressup/home",
    "/api/player/style/list", "/api/v1/player/style/list",
    "/api/playsquare/style/list", "/api/dress/product/list",
    "/api/dress/category/list", "/api/dress/config/get",
    "/api/content/dress/style/list", "/api/middle/dress/style/list",
    "/api/middle/clientcfg/config/pushed/list",
]


def cmd_probe():
    if not os.path.exists(SESSION):
        print("NO SESSION, login first"); return
    p = json.load(open(SESSION))
    ck = p.get("cookies") or {}
    cookie = "; ".join(f"{k}={v}" for k, v in ck.items())
    if p.get("set_cookie"):
        cookie = cookie + "; " + p["set_cookie"].split(";")[0] if cookie else p["set_cookie"].split(";")[0]
    print("cookie keys", list(ck.keys()), "music_u", "MUSIC_U" in cookie)
    out = []
    for path in DRESS_PATHS:
        try:
            if path.startswith("/weapi/"):
                r = sess(cookie).post("https://music.163.com" + path,
                                      data=weapi({"e_r": True, "header": {}, "limit": 50, "offset": 0,
                                                  "csrf_token": ck.get("__csrf", "")}), timeout=8)
            else:
                r = sess(cookie).get("https://music.163.com" + path,
                                     params={"limit": 50, "offset": 0}, timeout=8)
            t = r.text[:400]
            if "接口未找到" in t or '"code":404' in t or t.strip() in ("", "{}"):
                continue
            out.append({"path": path, "status": r.status_code, "body": t})
            print("HIT", path, "|", t[:180].replace("\n", " "), flush=True)
        except Exception as e:
            pass
    with open(PROBE_OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("HITS", len(out), "->", PROBE_OUT, flush=True)


# ---------- 供 Web 端调用的可复用接口（按需实时生成，避免二维码过期） ----------

UNIKEY_URL = "https://music.163.com/weapi/login/qrcode/unikey"
CHECK_URL = "https://music.163.com/weapi/login/qrcode/client/login"


def new_key():
    """向网易云申请一枚全新的扫码 key（有效期几分钟，故必须按需生成）。"""
    r = sess().post(UNIKEY_URL, data=weapi({"type": 1, "csrf_token": ""}), timeout=10)
    return r.json().get("unikey") or ""


def qr_png(key):
    """把 codekey 变成纯二维码 PNG 字节流（不落静态目录，不写入部署包）。"""
    import io
    import qrcode
    url = "https://music.163.com/login?codekey=" + key
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=4)
    q.add_data(url); q.make(fit=True)
    img = q.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO(); img.save(buf, format="PNG")
    return buf.getvalue()


def check(key):
    """查询扫码状态。返回 (json, cookies_dict, set_cookie, raw_text)。"""
    s = sess()
    r = s.post(CHECK_URL, data=weapi({"key": key, "type": 1, "csrf_token": ""}), timeout=10)
    try:
        j = r.json()
    except Exception:
        j = {}
    return j, s.cookies.get_dict(), r.headers.get("Set-Cookie", ""), r.text[:600]


def save_session(cookies, set_cookie, raw):
    """登录态只写本地文件，权限 600；不进 static/、不进 history、不进仓库。"""
    os.makedirs(DATA, exist_ok=True)
    payload = {"cookies": cookies, "set_cookie": set_cookie,
               "raw": raw, "ts": int(time.time())}
    with open(SESSION, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.chmod(SESSION, 0o600)
    return payload


def has_session():
    if not os.path.exists(SESSION):
        return False
    try:
        p = json.load(open(SESSION))
        c = p.get("cookies") or {}
        return bool(c.get("MUSIC_U")) or "MUSIC_U=" in (p.get("set_cookie") or "")
    except Exception:
        return False


def session_cookie():
    if not os.path.exists(SESSION):
        return ""
    p = json.load(open(SESSION))
    ck = p.get("cookies") or {}
    cookie = "; ".join(f"{k}={v}" for k, v in ck.items())
    sc = p.get("set_cookie") or ""
    if sc and "MUSIC_U=" in sc and "MUSIC_U=" not in cookie:
        cookie = (cookie + "; " if cookie else "") + sc.split(";")[0]
    return cookie


def probe(cookie=""):
    """带登录态撞装扮中心私有接口，返回命中的真实响应。"""
    hdr = {"osver": "17.0", "appver": "9.4.25", "os": "ios",
           "channel": "netease", "reqId": str(int(time.time() * 1000))}
    csrf = ""
    if cookie:
        for seg in cookie.split(";"):
            if "__csrf=" in seg:
                csrf = seg.split("=", 1)[1].strip()
    hits = []
    for path in DRESS_PATHS:
        try:
            if path.startswith("/weapi/"):
                body = {"e_r": True, "header": hdr, "limit": 50, "offset": 0,
                        "csrf_token": csrf}
                r = sess(cookie).post("https://music.163.com" + path,
                                      data=weapi(body), timeout=8)
            else:
                r = sess(cookie).get("https://music.163.com" + path,
                                     params={"limit": 50, "offset": 0,
                                             "moduleName": "dress"}, timeout=8)
            t = r.text[:600]
            if "接口未找到" in t or '"code":404' in t or t.strip() in ("", "{}"):
                continue
            if '"data":{}' in t.replace(" ", ""):
                continue
            hits.append({"path": path, "status": r.status_code, "body": t})
        except Exception:
            pass
    return hits


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "key"
    if cmd == "key":
        cmd_key()
    elif cmd == "watch":
        cmd_watch(sys.argv[2])
    elif cmd == "probe":
        cmd_probe()

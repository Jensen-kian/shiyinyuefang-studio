# -*- coding: utf-8 -*-
"""专辑 CD 装帧全套素材生成（纯本地，无 AI 依赖）。
输入：封面图(PIL)、色板(palette)、专辑参数(params) → 输出 10 张同名同尺寸图 + A4 拼版 + zip。
尺寸体系与"范特西 zip"逐张对齐（CANON 固定）。
"""
import os, math, random, zipfile
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
from fontTools.ttLib import TTFont as FTFont

from . import palette as pal
from .barcode import build_barcode

FONTS = os.path.join(os.path.dirname(__file__), "..", "fonts")
DEJA = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# ---------- 尺寸体系：70.6 px/mm（与范特西zip一致的高分辨率画布） ----------
S = 70.6
def mm(v): return int(round(v * S))
DISC = mm(40)            # 2824
COVER = mm(41)           # 2896
STRIP_W, STRIP_H = mm(4.4), mm(38)     # 311 x 2688
BACK_W, BACK_H = mm(49), mm(38)        # 3464 x 2688
A4 = (2480, 3508)
OVERVIEW = (3134, 1290)

FT = {
    "frak":   os.path.join(FONTS, "UnifrakturMaguntia.ttf"),
    "sans":   os.path.join(FONTS, "NotoSansCJKsc.otf"),
    "sansb":  os.path.join(FONTS, "NotoSansCJKsc-Bold.otf"),
    "serif":  os.path.join(FONTS, "NotoSerifSC.ttf"),
    "script": os.path.join(FONTS, "GreatVibes.ttf"),
    "cinzel": os.path.join(FONTS, "Cinzel.ttf"),
}
def font(key, size):
    return ImageFont.truetype(FT[key], size)
def dfont(size):
    return ImageFont.truetype(DEJA, size)

_cmap_cache = {}
def has_glyph(key, ch):
    if key not in _cmap_cache:
        _cmap_cache[key] = FTFont(FT[key]).getBestCmap()
    return ord(ch) in _cmap_cache[key]

def pick_font_for(text, prefer=("frak", "cinzel", "sans")):
    """按字形可用性挑选字体，保证标题不缺字。"""
    for k in prefer:
        if all(has_glyph(k, c) for c in text):
            return k
    return "sans"

def _safe(text, key):
    """丢弃当前字体 cmap 中不存在的字符，避免缺字方框（如韩元符号 ￦）。"""
    if not text:
        return text
    cm = _cmap_cache.setdefault(key, FTFont(FT[key]).getBestCmap())
    return "".join(c for c in text if ord(c) in cm)


# ---------- 程序化云海纹理（stops 由封面色板派生） ----------
def _noise_layer(w, h, cells, rng):
    small = (rng.random((cells, cells)) * 255).astype(np.uint8)
    im = Image.fromarray(small).resize((w, h), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 255.0

def cloud_texture(w, h, seed=7, stops=None):
    rng = np.random.default_rng(seed)
    acc = np.zeros((h, w), np.float32); amp = 1.0; tot = 0.0
    for cells in (3, 5, 9, 17, 33, 65):
        acc += _noise_layer(w, h, cells, rng) * amp
        tot += amp; amp *= 0.62
    n = acc / tot
    n = (n - n.min()) / (n.max() - n.min())
    n = np.clip((n - 0.5) * 1.55 + 0.5, 0, 1) ** 1.15
    if stops is None:
        stops = [(0.0, (26, 15, 6)), (0.35, (96, 52, 15)), (0.62, (190, 118, 40)),
                 (0.85, (226, 178, 105)), (1.0, (244, 228, 198))]
    xs = np.array([p[0] for p in stops]); cs = np.array([p[1] for p in stops], np.float32)
    img = np.zeros((h, w, 3), np.float32)
    for c in range(3):
        img[..., c] = np.interp(n, xs, cs[:, c])
    im = Image.fromarray(img.astype(np.uint8))
    # 柔光
    glow = Image.new("L", (w, h), 0); gd = ImageDraw.Draw(glow)
    gx, gy, gr = int(w*0.5), int(h*0.34), int(min(w, h)*0.52)
    gd.ellipse([gx-gr, gy-gr, gx+gr, gy+gr], fill=95)
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h)//7))
    im = Image.composite(ImageEnhance.Brightness(im).enhance(1.28), im, glow)
    # 光束
    rays = Image.new("L", (w, h), 0); rd = ImageDraw.Draw(rays)
    for i, (ang, wd) in enumerate([(-24, 60), (8, 36), (32, 78), (-52, 30)]):
        cx, cy = int(w*(0.3+0.15*i)), int(h*0.28)
        L = int(max(w, h)*0.9); a = math.radians(ang)
        dx, dy = math.sin(a), -math.cos(a); px, py = -dy*wd, dx*wd
        rd.polygon([(cx, cy), (cx+dx*L+px, cy+dy*L+py), (cx+dx*L-px, cy+dy*L-py)], fill=70)
    rays = rays.filter(ImageFilter.GaussianBlur(min(w, h)//14))
    im = Image.composite(ImageEnhance.Brightness(im).enhance(1.22), im, rays)
    # 暗角
    vig = Image.new("L", (w, h), 0); vd = ImageDraw.Draw(vig)
    m = int(min(w, h)*0.18); vd.ellipse([-m, -m, w+m, h+m], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(min(w, h)//8))
    dark = ImageEnhance.Brightness(im).enhance(0.62)
    im = Image.composite(im, dark, vig)
    # 颗粒
    g = (np.asarray(im, np.float32) + rng.normal(0, 3.2, (h, w, 1)).repeat(3, axis=2)).clip(0, 255).astype(np.uint8)
    return Image.fromarray(g)

def add_bokeh(im, seed, count=26, rmin=4, rmax=26, alpha=70, tint=(255, 236, 200)):
    w, h = im.size; rng = random.Random(seed)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    for _ in range(count):
        r = rng.randint(rmin, rmax); x, y = rng.randint(0, w), rng.randint(0, h)
        d.ellipse([x-r, y-r, x+r, y+r], fill=(*tint, rng.randint(alpha//2, alpha)))
    layer = layer.filter(ImageFilter.GaussianBlur(2))
    out = im.convert("RGBA"); out.alpha_composite(layer); return out.convert("RGB")


# ---------- 文字工具 ----------
def fit_font(key, text, max_w, start, tracking=0):
    size = start
    while size > 8:
        f = font(key, size)
        wsum = sum(f.getlength(c) for c in text) + tracking*(len(text)-1)
        if wsum <= max_w: return f, wsum
        size = int(size*0.96)
    return font(key, 8), 0

def draw_tracked(draw, xy, text, f, fill, tracking=0, anchor_y="top"):
    ay = {"top": "a", "m": "m"}.get(anchor_y, "a")
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill, anchor=f"l{ay}")
        x += f.getlength(ch) + tracking
    return x

def center_text_w(text, f, tracking=0):
    return sum(f.getlength(c) for c in text) + tracking*(len(text)-1)

def vertical_text(text, f, fill, pad=20, rot=-90):
    asc, desc = f.getmetrics()
    W = int(sum(f.getlength(c) for c in text)) + pad*2
    H = asc + desc + pad*2
    tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(tmp)
    x = pad
    for ch in text:
        d.text((x, pad), ch, font=f, fill=fill); x += f.getlength(ch)
    return tmp.rotate(rot, expand=True)

def vtext(text, size, fill, prefer=("cinzel", "sans")):
    """竖排文字：自动选字体并过滤缺字字符。"""
    key = pick_font_for(text, prefer)
    return vertical_text(_safe(text, key), font(key, size), fill)


def quote_with_heart(draw, cx, y, text, fserif, fill, heart_ratio=1.06):
    if not text:
        return
    fsym = font("sansb", int(fserif.size * heart_ratio))
    w = fserif.getlength(text) + fsym.getlength("♡") * 0.9
    x = cx - w / 2
    draw.text((x, y), text, font=fserif, fill=fill, anchor="lm")
    draw.text((x + fserif.getlength(text) + fsym.getlength("♡")*0.28, y),
              "♡", font=fsym, fill=fill, anchor="lm")


def _square_crop(img):
    w, h = img.size
    s = min(w, h)
    return img.crop(((w-s)//2, (h-s)//2, (w-s)//2 + s, (h-s)//2 + s))


# ============================ 主生成函数 ============================
def generate(cover_img, palette, params, out_dir, seed=7):
    os.makedirs(out_dir, exist_ok=True)
    P = params
    artist = P.get("artist", "")
    album = P.get("album", "")
    year = P.get("year", "")
    label = P.get("label", "")
    ean = "".join(ch for ch in P.get("ean", "") if ch.isdigit())
    tracks = P.get("tracks", [])
    ink = palette["ink"]; brown = palette["brown"]; gold = palette["gold"]; cream = palette["cream"]

    rd_deep, rd_light, rd_mid = pal.ramp_deep(palette), pal.ramp_light(palette), pal.ramp_mid(palette)

    # 1. 封面（使用上传封面，等比提升）
    cover = _square_crop(cover_img).resize((COVER, COVER), Image.LANCZOS)
    cover = cover.filter(ImageFilter.UnsharpMask(radius=3, percent=90, threshold=2))
    cover = ImageEnhance.Contrast(cover).enhance(1.03)
    cover.save(os.path.join(out_dir, "1-封面.png"))

    # 2. 盘面
    disc_tex = cloud_texture(DISC, DISC, seed=seed+4, stops=rd_deep)
    disc = add_bokeh(disc_tex, seed+35, count=34, rmin=5, rmax=30, alpha=80,
                     tint=palette["cream"]).convert("RGBA")
    d = ImageDraw.Draw(disc)
    dtitle = album if album else "ALBUM"
    fk = pick_font_for(dtitle, ("frak", "cinzel", "sans"))
    ft, _ = fit_font(fk, dtitle, int(DISC*0.92), 400)
    d.text((DISC/2+6, DISC*0.415+7), _safe(dtitle, fk), font=ft,
           fill=(*palette["ink"], 130), anchor="mm")
    d.text((DISC/2, DISC*0.415), _safe(dtitle, fk), font=ft, fill=cream, anchor="mm")
    f2 = font("cinzel", 92)
    disc_sub = P.get("disc_sub") or f"ALBUM · {year}" if year else (P.get("disc_sub") or "ALBUM")
    disc_sub = _safe(disc_sub, "cinzel")
    draw_tracked(d, (DISC/2 - center_text_w(disc_sub, f2, 46)/2, DISC*0.605), disc_sub, f2, gold, 46)
    f3 = font("sans", 58)
    aly = _safe((f"{artist} · {album}".upper() if artist else album.upper()), "sans")
    draw_tracked(d, (DISC/2 - center_text_w(aly, f3, 26)/2, DISC*0.675), aly, f3, gold, 26)
    small = font("sans", 46)
    draw_tracked(d, (DISC/2 - center_text_w(_safe(label.upper(), "sans"), small, 18)/2, DISC*0.815),
                 _safe(label.upper(), "sans"), small, (cream[0], cream[1], cream[2], 215), 18)
    mask = Image.new("L", (DISC, DISC), 0); md = ImageDraw.Draw(mask); c = DISC/2
    md.ellipse([2, 2, DISC-3, DISC-3], fill=255)
    hole_r = mm(5)/2; md.ellipse([c-hole_r, c-hole_r, c+hole_r, c+hole_r], fill=0)
    disc.putalpha(mask)
    disc.save(os.path.join(out_dir, "盘面.png"))

    # 3. 封面背面
    tex = cloud_texture(COVER, COVER, seed=seed+16, stops=rd_light)
    bb = tex.convert("RGBA"); bd = ImageDraw.Draw(bb)
    if P.get("back_quote1"):
        fq1 = font("serif", 300)
        quote_with_heart(bd, COVER/2, COVER*0.30, P["back_quote1"], fq1, ink)
    if P.get("back_quote2"):
        fq1b, _ = fit_font("serif", P["back_quote2"], COVER*0.80, 300)
        quote_with_heart(bd, COVER/2, COVER*0.44, P["back_quote2"], fq1b, ink)
    if P.get("back_script"):
        fq2 = font("script", 190)
        bd.text((COVER/2, COVER*0.60), P["back_script"], font=fq2, fill=brown, anchor="mm")
        bd.text((COVER/2, COVER*0.70), P.get("back_script2", ""), font=fq2, fill=brown, anchor="mm")
    if P.get("back_sub"):
        fsm = font("sans", 62)
        line = P["back_sub"]
        w_line = center_text_w(line, fsm, 14)
        draw_tracked(bd, (COVER/2 - w_line/2, COVER*0.885), line, fsm, brown, 14, anchor_y="m")
    bb.convert("RGB").save(os.path.join(out_dir, "2-封面背面.png"))

    # 4. 封底
    tex = cloud_texture(BACK_W, BACK_H, seed=seed+24, stops=rd_light)
    bk = tex.convert("RGBA")
    veil = Image.new("RGBA", (BACK_W, BACK_H), (0, 0, 0, 0)); vd = ImageDraw.Draw(veil)
    for i in range(6):
        vd.rectangle([0, 0, int(BACK_W*0.78) - i*30, BACK_H], fill=(*palette["cream"], 46))
    bk.alpha_composite(veil)
    bd = ImageDraw.Draw(bk)
    fh = font("cinzel", 150)
    artist_u = _safe(artist.upper(), "cinzel")
    draw_tracked(bd, (mm(2.6), mm(1.6)), artist_u, fh, ink, 12)
    fa = font("sans", 72)
    album_u = _safe(f"ALBUM {album.upper()}", "sans")
    aw = center_text_w(album_u, fa, 10)
    bd.text((mm(2.6) + fh.getlength(artist_u) + 12 + mm(3.5), mm(1.6)+96),
            album_u, font=fa, fill=brown, anchor="lm")
    # 版权行内容（先确定行数，供曲目区自适应计算可用高度）
    fc = font("sans", 50)
    owner = label.upper() if label else artist.upper() or "UNKNOWN"
    cops = [
        f"© {year} {owner}." if year else f"© {owner}.",
        "All rights reserved. Unauthorized copying, reproduction, hiring, lending,",
        "public performance and broadcasting prohibited.",
    ]
    if P.get("copyright_extra"):
        cops = P["copyright_extra"]
    line_h = 84

    # 曲目列表（自适应：曲目多时自动压缩行距与字号，永不压到版权行）
    n_tr = max(len(tracks), 1)
    top_y = mm(7.0)
    bottom_reserve = 190 + len(cops) * line_h + mm(2.2)   # 版权区 + 底部留白
    avail = BACK_H - bottom_reserve - top_y
    extra_h = mm(0.5) * sum(1 for t in tracks if t.get("sub"))
    raw_gap = (avail - extra_h) / n_tr
    row_gap = int(min(mm(2.6), max(min(mm(1.5), raw_gap), mm(1.0))))
    scale = max(0.48, min(1.0, raw_gap / mm(2.6)))
    y = top_y
    fn = font("sansb", int(108*scale)); ftit = font("sansb", int(118*scale))
    fsub = font("sans", int(66*scale)); ftm = font("sans", int(96*scale))
    sub_off = int(64*scale)
    xt_num, xt_title, xt_time = mm(2.6), mm(6.4), mm(35.2)
    for t in tracks:
        num = t.get("num", ""); title = t.get("title", ""); sub = t.get("sub"); dur = t.get("dur", "")
        bd.text((xt_num, y), num, font=fn, fill=brown, anchor="lm")
        bd.text((xt_title, y), _safe(title, "sansb"), font=ftit, fill=ink, anchor="lm")
        bd.text((xt_time, y), dur, font=ftm, fill=brown, anchor="rm")
        if sub:
            bd.text((xt_title, y + sub_off), _safe(sub, "sans"), font=fsub, fill=brown, anchor="lm")
            y += mm(0.5)
        y += row_gap
    # 手写标语（右上，斜置）
    if P.get("tagline"):
        fs = font("script", 135)
        sl = Image.new("RGBA", (mm(15), mm(22)), (0, 0, 0, 0)); sd = ImageDraw.Draw(sl)
        sd.text((mm(7.5), mm(11)), P["tagline"], font=fs, fill=brown, anchor="mm", align="center")
        sl = sl.rotate(-8, expand=True, resample=Image.BICUBIC)
        bk.alpha_composite(sl, (int(BACK_W*0.645), int(BACK_H*0.10)))
    # 版权行（贴底绘制）
    cy = BACK_H - 190 - (len(cops) - 1) * line_h
    for cl in cops:
        bd.text((90, cy), cl, font=fc, fill=brown, anchor="lm")
        cy += line_h
    # 条形码
    if ean and len(ean) == 13:
        bcl = build_barcode(ean, mm(17.0))
        bbx = BACK_W - mm(1.2) - bcl.width - mm(0.8)
        bby = BACK_H - mm(1.2) - bcl.height - mm(0.8)
        padbox = Image.new("RGBA", (bcl.width + mm(1.6), bcl.height + mm(1.2)), (255, 255, 255, 252))
        bk.alpha_composite(padbox, (bbx, bby))
        bk.alpha_composite(bcl.convert("RGBA"), (bbx + mm(0.8), bby + mm(0.6)))
    bk.convert("RGB").save(os.path.join(out_dir, "4-封底.png"))

    # 5. 右侧封
    def strip_panel(seed_, stops):
        t = cloud_texture(STRIP_W*3, STRIP_H*3, seed=seed_, stops=stops)
        return t.resize((STRIP_W, STRIP_H), Image.LANCZOS)
    rs = strip_panel(seed+48, rd_deep).convert("RGBA"); rd = ImageDraw.Draw(rs)
    fdeco = dfont(110)
    rd.text((STRIP_W/2, mm(2.8)), "✦", font=fdeco, fill=(255, 236, 196, 225), anchor="mm")
    vt = vtext(artist.upper(), 128, cream)
    rs.alpha_composite(vt, (int(STRIP_W/2 - vt.width/2), int(mm(5.2))))
    vt2 = vtext(album.upper(), 96, gold)
    rs.alpha_composite(vt2, (int(STRIP_W/2 - vt2.width/2), int(mm(5.2) + vt.height + mm(1.6))))
    vt3 = vtext(f"ALBUM · {year}" if year else "ALBUM", 62, (255, 224, 178, 240))
    rs.alpha_composite(vt3, (int(STRIP_W/2 - vt3.width/2), STRIP_H - vt3.height - mm(2.2)))
    rs.convert("RGB").save(os.path.join(out_dir, "3-右侧封.png"))

    # 6. 左侧封
    ls = strip_panel(seed+59, rd_deep).convert("RGBA"); ld = ImageDraw.Draw(ls)
    ld.text((STRIP_W/2, mm(2.6)), "✦", font=fdeco, fill=(255, 236, 196, 215), anchor="mm")
    vt4 = vtext(album.upper(), 112, cream)
    ls.alpha_composite(vt4, (int(STRIP_W/2 - vt4.width/2), int(mm(4.8))))
    vt5 = vtext(artist.upper(), 92, gold)
    ls.alpha_composite(vt5, (int(STRIP_W/2 - vt5.width/2), int(mm(4.8) + vt4.height + mm(1.4))))
    vt6 = vtext(label.upper(), 58, (255, 224, 178, 240))
    ls.alpha_composite(vt6, (int(STRIP_W/2 - vt6.width/2), STRIP_H - vt6.height - mm(2.0)))
    ls.convert("RGB").save(os.path.join(out_dir, "5-左侧封.jpg"), quality=95)

    # 7. 左侧封背面
    lb = strip_panel(seed+70, rd_deep)
    lb.save(os.path.join(out_dir, "6-左侧封背面.png"))

    # 8. 内盘底
    tex = cloud_texture(BACK_W, BACK_H, seed=seed+92, stops=rd_mid)
    ib = tex.convert("RGBA")
    glow = Image.new("L", (BACK_W, BACK_H), 0); gd2 = ImageDraw.Draw(glow)
    gd2.ellipse([BACK_W*0.18, BACK_H*0.12, BACK_W*0.82, BACK_H*0.88], fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    ib = Image.composite(ImageEnhance.Brightness(ib).enhance(1.30), ib, glow)
    idr = ImageDraw.Draw(ib)
    if P.get("inner_quote1"):
        fq3 = font("serif", 260)
        quote_with_heart(idr, BACK_W/2, BACK_H*0.33, P["inner_quote1"], fq3, ink)
    if P.get("inner_quote2"):
        fq4, _ = fit_font("serif", P["inner_quote2"], BACK_W*0.72, 260)
        quote_with_heart(idr, BACK_W/2, BACK_H*0.50, P["inner_quote2"], fq4, ink)
    if P.get("inner_script"):
        fs2 = font("script", 165)
        idr.text((BACK_W/2, BACK_H*0.68), P["inner_script"], font=fs2, fill=brown, anchor="mm")
    if P.get("inner_sub"):
        fsm4 = font("sans", 64)
        line2 = P["inner_sub"]
        w2 = center_text_w(line2, fsm4, 14)
        draw_tracked(idr, (BACK_W/2 - w2/2, BACK_H*0.885), line2, fsm4, cream, 14, anchor_y="m")
    ib.convert("RGB").save(os.path.join(out_dir, "7-内盘底.png"))

    # 9. A4 拼版
    PPI = 300 / 25.4
    def pmm(v): return int(round(v * PPI))
    a4 = Image.new("RGB", A4, (255, 255, 255)); ad = ImageDraw.Draw(a4)
    cv_p = Image.open(os.path.join(out_dir, "1-封面.png")).convert("RGB").resize((pmm(41),)*2, Image.LANCZOS)
    bb_p = Image.open(os.path.join(out_dir, "2-封面背面.png")).convert("RGB").resize((pmm(41),)*2, Image.LANCZOS)
    strip_p = Image.new("RGB", (pmm(111.2), pmm(38)))
    strip_folds = []; xoff = 0
    for name, wmm in [("3-右侧封.png", 4.4), ("4-封底.png", 49), ("5-左侧封.jpg", 4.4),
                      ("6-左侧封背面.png", 4.4), ("7-内盘底.png", 49)]:
        im = Image.open(os.path.join(out_dir, name)).convert("RGB")
        strip_p.paste(im.resize((pmm(wmm), pmm(38)), Image.LANCZOS), (xoff, 0)); xoff += pmm(wmm)
        if wmm in (4.4, 49) and xoff < pmm(111.2):
            strip_folds.append(xoff)
    COVERp = pmm(41); STRIP_Hp = pmm(38); STRIP_Wp = pmm(111.2); N = 7
    TOP = (A4[1] - N * COVERp) // 2
    LX = (A4[0] - (2 * COVERp + STRIP_Wp)) // 2
    RX = LX + 2 * COVERp
    for i in range(N):
        y = TOP + i * COVERp
        a4.paste(bb_p, (LX, y)); a4.paste(cv_p, (LX + COVERp, y))
    for i in range(N):
        y = TOP + i * STRIP_Hp
        a4.paste(strip_p, (RX, y))
    SEAM = 2
    def seam_v(x, y0, y1):
        ad.rectangle([x - SEAM//2, y0, x + SEAM//2, y1], fill=(255, 255, 255))
    def seam_h(y, x0, x1):
        ad.rectangle([x0, y - SEAM//2, x1, y + SEAM//2], fill=(255, 255, 255))
    seam_v(LX + COVERp, TOP, TOP + N * COVERp)
    seam_v(RX, TOP, TOP + N * STRIP_Hp)
    for fx in strip_folds:
        seam_v(RX + fx, TOP, TOP + N * STRIP_Hp)
    for i in range(1, N):
        seam_h(TOP + i * COVERp, LX, LX + 2 * COVERp)
    for i in range(1, N):
        seam_h(TOP + i * STRIP_Hp, RX, RX + STRIP_Wp)
    CL = (90, 90, 90); RXW = RX + STRIP_Wp; CB = TOP + N * COVERp
    ad.line([0, TOP, LX, TOP], fill=CL, width=3)
    ad.line([RXW, TOP, A4[0], TOP], fill=CL, width=3)
    ad.line([LX, CB, LX, A4[1]], fill=CL, width=3)
    ad.line([LX + 2 * COVERp, CB, LX + 2 * COVERp, A4[1]], fill=CL, width=3)
    yb = TOP + N * STRIP_Hp
    ad.line([RXW, yb, A4[0], yb], fill=CL, width=3)
    a4.save(os.path.join(out_dir, "A4打印.jpg"), quality=92)

    # 10. 版面总览
    ov = Image.new("RGB", OVERVIEW, (255, 255, 255)); od = ImageDraw.Draw(ov)
    s = OVERVIEW[1] / 1290 * 11.0
    def omm(v): return int(round(v * s))
    od.text((60, 56), f"{artist} 《{album}》 印刷版图（展开图）", font=font("sansb", 56), fill=(40, 40, 40), anchor="la")
    od.text((60, 130), "① 盘面（CD光盘）外直径40mm · 内直径5mm      ② 封面背面+封面（展开 82mm×41mm）      ③ 右侧封+封底+左侧封+左侧封背面+内盘底（展开 111.2mm×38mm）",
            font=font("sans", 34), fill=(110, 110, 110), anchor="la")
    row_c = 300 + omm(20)
    dd = Image.open(os.path.join(out_dir, "盘面.png")).convert("RGBA").resize((omm(40),)*2, Image.LANCZOS)
    ov.paste(dd, (70, row_c), dd)
    od.text((70 + omm(20), row_c + omm(40) + 18), "外直径40mm 内直径5mm", font=font("sans", 30), fill=(120, 120, 120), anchor="ma")
    x2 = 70 + omm(40) + 80
    ov.paste(bb_p.resize((omm(41),)*2, Image.LANCZOS), (x2, row_c))
    ov.paste(cv_p.resize((omm(41),)*2, Image.LANCZOS), (x2 + omm(41), row_c))
    od.line([x2+omm(41), row_c-14, x2+omm(41), row_c+omm(41)+14], fill=(170, 170, 170), width=3)
    od.text((x2, row_c-26), "封面背面（41×41mm）", font=font("sans", 30), fill=(120, 120, 120), anchor="lb")
    od.text((x2+omm(41), row_c-26), "封面（41×41mm）", font=font("sans", 30), fill=(120, 120, 120), anchor="lb")
    x3 = x2 + omm(82) + 90; xx = x3
    for name, wmm, label_txt in [("3-右侧封.png", 4.4, "右侧封\n4.4mm"), ("4-封底.png", 49, "封底\n49mm"),
                                 ("5-左侧封.jpg", 4.4, "左侧封\n4.4mm"), ("6-左侧封背面.png", 4.4, "左侧封背面\n4.4mm"),
                                 ("7-内盘底.png", 49, "内盘底\n49mm")]:
        imp = Image.open(os.path.join(out_dir, name)).convert("RGB").resize((omm(wmm), omm(38)), Image.LANCZOS)
        ov.paste(imp, (xx, row_c))
        if wmm != 49:
            od.line([xx+omm(wmm), row_c-14, xx+omm(wmm), row_c+omm(38)+14], fill=(170, 170, 170), width=3)
        lx = xx + omm(wmm)/2
        for i, ln in enumerate(label_txt.split("\n")):
            od.text((lx, row_c + omm(38) + 14 + i*36), ln, font=font("sans", 28), fill=(120, 120, 120), anchor="ma")
        xx += omm(wmm)
    od.text((x3, row_c - 26), "折直角→先对折→再折直角→再折直角", font=font("sans", 28), fill=(150, 150, 150), anchor="lb")
    od.text((OVERVIEW[0]-60, OVERVIEW[1]-40), f"{artist} · {album} · {year}",
            font=font("sans", 30), fill=(150, 150, 150), anchor="rs")
    ov.save(os.path.join(out_dir, "★版面总览-1比1.png"))

    # 11. 尺寸对齐（与范特西zip逐张一致）
    CANON = {
        "1-封面.png": (1177, 1177), "2-封面背面.png": (847, 847),
        "3-右侧封.png": (472, 4080), "4-封底.png": (1404, 1089),
        "5-左侧封.jpg": (472, 4080), "6-左侧封背面.png": (472, 4080),
        "7-内盘底.png": (1054, 817), "盘面.png": (2824, 2824),
        "A4打印.jpg": (2480, 3508), "★版面总览-1比1.png": (3134, 1290),
    }
    for name, size in CANON.items():
        p = os.path.join(out_dir, name)
        im = Image.open(p)
        if im.mode == "RGBA" and name == "盘面.png":
            im = im.resize(size, Image.LANCZOS)
        else:
            im = im.convert("RGB").resize(size, Image.LANCZOS)
            if name.endswith(".jpg"):
                im.save(p, quality=93)
            else:
                im.save(p)
    # 压缩包
    zip_path = os.path.join(out_dir, f"{artist}_{album}_专辑素材.zip".replace(" ", ""))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in CANON:
            z.write(os.path.join(out_dir, name), arcname=name)
    return {
        "files": {k: os.path.join(out_dir, k) for k in CANON},
        "zip": zip_path,
        "out_dir": out_dir,
    }

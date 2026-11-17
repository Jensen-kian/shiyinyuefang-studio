# -*- coding: utf-8 -*-
"""钥匙扣商品图 —— 按「唱片封面」播放器样式参数化重绘内腔。

设计要点（与用户确认的机制一致）：
  1. 内嵌播放器是 30×50mm（3:5）的网易云「唱片封面」版式；
  2. **样式只是版式骨架**：播放器背景（纯色/光影）、唱片封面（经典/做旧），
     由用户在制作页自行选择并实时改变呈现；
  3. **内容全部来自当前歌曲**：方形专辑封面、歌名、歌手、时长、进度、
     VIP/关注/热度，以及背景主色（取当前歌曲封面主色压暗降饱和）。
     绝不贴官方装扮演示图（那张自带 Blur / MØ / FOREVERLAND）。
  4. 原型贴片用 GitHub 原仓库 assets：keychain_overlay.png(1920) /
     clear_square_ring_overlay.png(1254)，内腔已镂空透明、原始分辨率不放大。
  5. 播放卡按内腔**精确像素尺寸**生成后直接贴入，不做 ImageOps.fit 裁切、
     不做二次缩放 → 边缘严丝合缝，不会「往左宽出」。

款式 key 与制作页保持一致：classic=长方形，square_ring=八角形。
"""
import os
import colorsys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageEnhance

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KC_DIR = os.path.join(BASE, "static", "keychain")
FONTS = os.path.join(BASE, "fonts")
BOLD = os.path.join(FONTS, "NotoSansCJKsc-Bold.otf")
REG = os.path.join(FONTS, "NotoSansCJKsc.otf")

# GitHub 原仓库 assets/keychain 贴片：bbox=含金属环的不透明外轮廓；
# inner=内腔（实测像素坐标，贴片本身已把该区域做成全透明）。
# 长方形 inner 452x754 = 0.5995，正好是 30x50mm 的 3:5。
BLANKS = {
    "classic": {
        "label": "长方形",
        "file": "keychain_overlay.png",
        "bbox": (688, 232, 1233, 1687),
        "inner": (732, 873, 1184, 1627),
    },
    "square_ring": {
        "label": "八角形",
        "file": "clear_square_ring_overlay.png",
        "bbox": (41, 21, 1193, 1227),
        "inner": (445, 555, 809, 1108),
    },
}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _int(v, d):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _font(size, bold=True):
    try:
        return ImageFont.truetype(BOLD if bold else REG, max(8, int(size)))
    except Exception:
        return ImageFont.load_default()


def _spec(style):
    return BLANKS.get(style, BLANKS["classic"])


def _blank_overlay(style):
    """原仓库贴片内腔已镂空透明，直接返回即可（无需再挖洞，保住原始清晰度）。"""
    sp = _spec(style)
    return Image.open(os.path.join(KC_DIR, sp["file"])).convert("RGBA")


def _dominant(cover):
    """取封面主色（出现占比最大的量化色）。"""
    try:
        q = cover.convert("RGB").resize((80, 80), Image.LANCZOS).quantize(colors=6)
        pal = q.getpalette()
        idx = sorted(q.getcolors(), reverse=True)[0][1]
        return tuple(pal[idx * 3:idx * 3 + 3])
    except Exception:
        return (150, 46, 40)


def _theme(cover):
    """由当前歌曲封面主色生成播放器背景：上亮下暗渐变，色相随封面。

    实测网易云「唱片封面」四张真实界面（1179x1964）：
      顶部 v≈0.20+0.29*s、底部 v≈顶部/1.85，饱和度≈min(s*0.72,0.66)。
      白色/低饱和封面 -> 中性深灰(《江南》45,45,45)；玫红 -> 酒红(On Clap 121,40,57)；
      绿 -> 橄榄绿(颜色 112,120,45)；棕 -> 深棕(某天 85,74,68)。
    返回 (top_rgb, bottom_rgb)。
    """
    r, g, b = _dominant(cover)
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    s2 = min(s * 0.72, 0.66)
    v_top = 0.20 + 0.29 * min(s, 1.0)
    v_bot = v_top / 1.85
    top = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, s2, v_top))
    bot = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, s2 * 0.94, v_bot))
    return top, bot


def _aged(im):
    """唱片封面「做旧」质感：轻微褪色泛黄 + 颗粒噪点 + 暗角。"""
    im = ImageEnhance.Color(im).enhance(0.70)
    im = ImageEnhance.Contrast(im).enhance(0.92)
    sepia = Image.new("RGB", im.size, (152, 124, 86))
    im = Image.blend(im, sepia, 0.13)
    arr = np.asarray(im).astype(np.int16)
    rng = np.random.default_rng(11)
    grain = rng.normal(0, 9, arr.shape[:2]).astype(np.int16)[:, :, None]
    arr = np.clip(arr + grain, 0, 255).astype(np.uint8)
    w, h = im.size
    Y, X = np.ogrid[:h, :w]
    cx, cy = w / 2.0, h / 2.0
    dist = np.sqrt(((X - cx) / (w / 2.0)) ** 2 + ((Y - cy) / (h / 2.0)) ** 2)
    vig = np.clip(1.0 - np.clip(dist - 0.55, 0, 1) * 0.85, 0, 1)[:, :, None]
    arr = np.clip(arr.astype(np.float32) * vig, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def _heart(d, x, y, s, color):
    d.ellipse([x - s, y - s, x, y], fill=color)
    d.ellipse([x, y - s, x + s, y], fill=color)
    d.polygon([(x - s, y + s * 0.15), (x + s, y + s * 0.15), (x, y + s * 1.1)], fill=color)


def _bubble(d, x, y, s, color):
    d.rounded_rectangle([x - s, y - s * 0.7, x + s, y + s * 0.5], radius=s * 0.35,
                        outline=color, width=max(1, round(s * 0.16)))
    d.polygon([(x - s * 0.25, y + s * 0.45), (x - s * 0.5, y + s * 0.95),
               (x + s * 0.05, y + s * 0.5)], fill=color)


def skin_card(cover, song="", artist="", album="", dur="", p=None, W=452, H=754):
    """网易云「唱片封面」播放器样式 —— 按 1179x1964 真实截图参数化重绘。

    版式骨架固定，内容全部来自当前歌曲；背景色相/明度随当前专辑封面。
    W,H 由调用方按钥匙扣内腔真实像素尺寸传入，与内腔 1:1 贴合。

    p 可选键：
      skin_bg    '纯色'(默认) / '光影'   背景处理
      skin_cover '经典'(默认) / '做旧'   唱片封面质感
      player_skin 选中的装扮样式 id（登记用，不贴官方演示图内容）
      vip / follow / hot_text / comment_text / auto_text / cur_time
    """
    p = p or {}
    W, H = max(60, int(W)), max(60, int(H))
    S = W / 1179.0                 # 横向与字号：以真实截图 1179 宽为设计稿
    rgb = cover.convert("RGB")
    top, bot = _theme(rgb)
    bg_mode = str(p.get("skin_bg") or "纯色")
    cover_mode = str(p.get("skin_cover") or "经典")

    # ---- 背景：自上而下线性渐变（真实约 1.85:1，非纯黑）----
    card = Image.new("RGB", (W, H), bot)
    d = ImageDraw.Draw(card)
    for y in range(H):
        t = y / float(H)
        c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)
    # 「光影」：中心偏上的柔和光晕 + 斜向光带
    if "光影" in bg_mode:
        glow = Image.new("L", (W, H), 0)
        gd = ImageDraw.Draw(glow)
        cx, cy = W // 2, int(H * 0.32)
        R = int(W * 0.80)
        for i in range(18):
            rr = R * (1 - i / 18.0)
            gd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=int(6 + i * 6))
        glow = glow.filter(ImageFilter.GaussianBlur(W * 0.07))
        bright = Image.new("RGB", (W, H), tuple(min(255, int(c * 1.85) + 16) for c in top))
        card = Image.composite(bright, card, glow)
        band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(band).polygon(
            [(int(W * 0.05), 0), (int(W * 0.40), 0),
             (int(W * 0.14), int(H * 0.56)), (int(W * -0.10), int(H * 0.56))],
            fill=(255, 255, 255, 22))
        band = band.filter(ImageFilter.GaussianBlur(W * 0.045))
        card = Image.alpha_composite(card.convert("RGBA"), band).convert("RGB")

    # ---- 方形唱片封面：左右留白 5.5%、顶部 3.9%、正方形、轻微圆角无白边 ----
    L = round(W * 0.055)
    side = W - 2 * L
    ctop = round(H * 0.039)
    if ctop + side > round(H * 0.655):        # 非 3:5 内腔保底：不压到歌名行
        side = round(H * 0.655) - ctop
        L = (W - side) // 2
    cov = ImageOps.fit(rgb, (side, side), Image.LANCZOS)
    if "做旧" in cover_mode:
        cov = _aged(cov)
    rad = max(2, round(10 * S))
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, side, side], radius=rad, fill=255)
    card.paste(cov, (L, ctop), mask)
    d = ImageDraw.Draw(card)

    WHITE = (238, 238, 240)
    MUTED = (172, 172, 176)
    DIM = (138, 138, 144)
    RED = (236, 76, 82)

    def F(px, bold=False):
        return _font(max(8, round(px * S)), bold)

    name = str(song or "未命名歌曲")
    ar = str(artist or "未知歌手")
    hot = str(p.get("hot_text") or "999w+")
    comment = str(p.get("comment_text") or "10w+")
    auto = str(p.get("auto_text") or "标准音质")
    quality = "标准音质" if auto in ("auto", "", "无损") else auto
    total = str(dur or "04:27")
    cur = str(p.get("cur_time") or "00:00")

    Y_NAME = round(H * 0.708)
    Y_ARTIST = round(H * 0.748)
    Y_PROG = round(H * 0.815)
    Y_TIME = round(H * 0.837)
    Y_CTRL = round(H * 0.940)

    # ---- 歌名 + VIP（灰色胶囊）+ 右侧红心/评论 ----
    # 歌名按可用宽度自适应缩字号（真实截图长歌名不截断，右侧要给 VIP + 红心留位）
    vip_on = bool(p.get("vip", True))
    hx = round(W * 0.700)
    avail = hx - L - round(20 * S) - (round(62 * S) + round(12 * S) if vip_on else 0)
    fpx = 46
    fn = F(fpx)
    while d.textlength(name, font=fn) > avail and fpx > 26:
        fpx -= 2
        fn = F(fpx)
    if d.textlength(name, font=fn) > avail:
        short = name
        while len(short) > 2 and d.textlength(short + "…", font=fn) > avail:
            short = short[:-1]
        name = short + "…"
    d.text((L, Y_NAME), name, font=fn, fill=WHITE)
    nw = d.textlength(name, font=fn)
    if vip_on:
        vx = L + nw + round(12 * S)
        vy = Y_NAME + round(8 * S)
        vw, vh = round(62 * S), round(30 * S)
        d.rounded_rectangle([vx, vy, vx + vw, vy + vh], radius=round(6 * S),
                            fill=(116, 116, 122))
        d.text((vx + round(9 * S), vy + round(3 * S)), "VIP", font=F(20), fill=WHITE)

    hy = Y_NAME + round(24 * S)
    _heart(d, hx, hy, round(20 * S), RED)
    d.text((hx + round(16 * S), Y_NAME + round(4 * S)), hot[:8], font=F(26, False), fill=MUTED)
    bx = round(W * 0.875)
    _bubble(d, bx, hy, round(18 * S), MUTED)
    d.text((bx + round(16 * S), Y_NAME + round(4 * S)), comment[:6], font=F(26, False), fill=MUTED)

    # ---- 歌手 + 关注（或 > 箭头）----
    fa = F(34, False)
    d.text((L, Y_ARTIST), ar, font=fa, fill=MUTED)
    aw = d.textlength(ar, font=fa)
    if p.get("follow", True):
        fx = L + aw + round(14 * S)
        fy = Y_ARTIST + round(3 * S)
        fw, fh = round(76 * S), round(34 * S)
        d.rounded_rectangle([fx, fy, fx + fw, fy + fh], radius=fh // 2,
                            fill=(108, 108, 114))
        d.text((fx + round(11 * S), fy + round(4 * S)), "关注", font=F(22, False), fill=WHITE)
    else:
        ax = L + aw + round(14 * S)
        ay = Y_ARTIST + round(16 * S)
        d.line([ax, ay - round(9 * S), ax + round(9 * S), ay], fill=MUTED, width=max(1, round(3 * S)))
        d.line([ax + round(9 * S), ay, ax, ay + round(9 * S)], fill=MUTED, width=max(1, round(3 * S)))

    # ---- 进度条 + 时间 / 音质 ----
    x0, x1 = L, W - L
    barh = max(2, round(3 * S))
    d.rounded_rectangle([x0, Y_PROG, x1, Y_PROG + barh], radius=barh // 2, fill=(104, 104, 110))
    def _sec(t):
        try:
            mm, ss = t.split(":")[:2]
            return int(mm) * 60 + int(ss)
        except Exception:
            return 0
    ratio = _sec(cur) / max(1, _sec(total))
    if ratio <= 0:
        ratio = 0.26
    ratio = min(ratio, 0.96)
    prog = x0 + (x1 - x0) * ratio
    d.rounded_rectangle([x0, Y_PROG, prog, Y_PROG + barh], radius=barh // 2, fill=WHITE)
    pr = round(9 * S)
    d.ellipse([prog - pr, Y_PROG + barh // 2 - pr, prog + pr, Y_PROG + barh // 2 + pr], fill=WHITE)
    ft = F(28, False)
    d.text((x0, Y_TIME), cur, font=ft, fill=DIM)
    qw = d.textlength(quality, font=ft)
    d.text(((W - qw) / 2, Y_TIME), quality, font=ft, fill=DIM)
    tw = d.textlength(total, font=ft)
    d.text((x1 - tw, Y_TIME), total, font=ft, fill=DIM)

    # ---- 底部 5 控件：循环 / 上一首 / 暂停(两条竖线) / 下一首 / 列表 ----
    cy = Y_CTRL
    lw = max(2, round(5 * S))
    u = round(38 * S)               # 控件半尺寸基准（对齐真实截图视觉大小）
    # 循环（开口圆环 + 箭头）
    rx = round(W * 0.095)
    rr = round(32 * S)
    d.arc([rx - rr, cy - rr, rx + rr, cy + rr], start=35, end=320, fill=WHITE, width=lw)
    d.polygon([(rx + rr - round(2 * S), cy - rr - round(9 * S)),
               (rx + rr + round(13 * S), cy - rr + round(2 * S)),
               (rx + rr - round(6 * S), cy - rr + round(8 * S))], fill=WHITE)
    # 上一首 |◀ / 下一首 ▶|
    for cx, sgn in ((round(W * 0.305), 1), (round(W * 0.695), -1)):
        if sgn > 0:
            d.polygon([(cx + u * 0.45, cy - u * 0.72), (cx + u * 0.45, cy + u * 0.72),
                       (cx - u * 0.5, cy)], fill=WHITE)
            d.rounded_rectangle([cx - u * 0.62, cy - u * 0.72,
                                 cx - u * 0.62 + lw, cy + u * 0.72], radius=lw // 2, fill=WHITE)
        else:
            d.polygon([(cx - u * 0.45, cy - u * 0.72), (cx - u * 0.45, cy + u * 0.72),
                       (cx + u * 0.5, cy)], fill=WHITE)
            d.rounded_rectangle([cx + u * 0.62 - lw, cy - u * 0.72,
                                 cx + u * 0.62, cy + u * 0.72], radius=lw // 2, fill=WHITE)
    # 暂停：两条白色圆角竖线（无圆底）
    pw = round(11 * S)
    ph = round(30 * S)
    gap = round(9 * S)
    for sx in (W // 2 - gap - pw, W // 2 + gap):
        d.rounded_rectangle([sx, cy - ph, sx + pw, cy + ph], radius=round(3 * S), fill=WHITE)
    # 列表：三条横线 + 左上小三角
    lx = round(W * 0.905)
    for k in range(3):
        yy = cy - round(22 * S) + k * round(22 * S)
        d.line([lx - round(24 * S), yy, lx + round(24 * S), yy], fill=WHITE, width=lw)
    d.polygon([(lx - round(30 * S), cy - round(30 * S)),
               (lx - round(18 * S), cy - round(22 * S)),
               (lx - round(30 * S), cy - round(14 * S))], fill=WHITE)
    return card


def _inner_card(cover, song, artist, album, dur, p, size):
    """内腔播放卡：始终按当前歌曲参数化重绘「唱片封面」版式，不贴官方演示图。"""
    w, h = int(size[0]), int(size[1])
    return skin_card(cover, song, artist, album, dur, p, max(60, w), max(60, h))


def _geometry(style, CW, CH, h_ratio):
    """计算原仓库贴片在画布上的缩放与内腔精确像素位置。"""
    sp = _spec(style)
    bx0, by0, bx1, by1 = sp["bbox"]
    s = (CH * h_ratio) / (by1 - by0)
    blank = _blank_overlay(style)
    ov = blank.resize((round(blank.width * s), round(blank.height * s)), Image.LANCZOS)
    px = round(CW / 2 - (bx0 + bx1) / 2 * s)
    py = round(CH / 2 - (by0 + by1) / 2 * s)
    ix0, iy0, ix1, iy1 = sp["inner"]
    inner = (round(px + ix0 * s), round(py + iy0 * s),
             round(px + ix1 * s), round(py + iy1 * s))
    return ov, (px, py), inner


_H_RATIO = 0.78


def scene_image(cover, style="classic", song="", artist="", album="", dur="", p=None):
    """钥匙扣商品图：模糊封面铺底 → 白框清晰封面 → 原仓库贴片 → 内腔播放卡。"""
    p = p or {}
    CW = CH = 1800
    rgb = cover.convert("RGB")

    zoom = 1.28
    big = ImageOps.fit(rgb, (round(CW * zoom), round(CH * zoom)), Image.LANCZOS)
    l, t = (big.width - CW) // 2, (big.height - CH) // 2
    bg = big.crop((l, t, l + CW, t + CH)).filter(ImageFilter.GaussianBlur(52))
    bg = Image.blend(bg, Image.new("RGB", (CW, CH), (10, 8, 10)), 0.10)
    scene = bg.convert("RGBA")

    m = round(CW * 0.075)
    border = 22
    d = ImageDraw.Draw(scene)
    d.rectangle([m, m, CW - m, CH - m], fill=(255, 255, 255, 255))
    ix = (m + border, m + border, CW - m - border, CH - m - border)
    scene.paste(ImageOps.fit(rgb, (ix[2] - ix[0], ix[3] - ix[1]), Image.LANCZOS),
                (ix[0], ix[1]))

    ov, (px, py), inner = _geometry(style, CW, CH, _H_RATIO)
    x0, y0, x1, y1 = inner
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(CW, x1), min(CH, y1)
    if x1 > x0 and y1 > y0:
        card = _inner_card(rgb, song, artist, album, dur, p, (x1 - x0, y1 - y0))
        scene.paste(card, (x0, y0))
    layer = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    layer.paste(ov, (px, py))
    scene = Image.alpha_composite(scene, layer)

    out = scene.convert("RGB")
    d = ImageDraw.Draw(out)
    if song:
        f = _font(62)
        t = str(song)
        if len(t) > 16:
            t = t[:15] + "…"
        w = d.textlength(t, font=f)
        tx = (CW - w) / 2
        d.text((tx + 3, 65), t, font=f, fill=(20, 18, 20))
        d.text((tx, 62), t, font=f, fill=(255, 255, 255))
    sub = (artist or "") + " · 歌曲钥匙扣"
    f2 = _font(34)
    w2 = d.textlength(sub, font=f2)
    d.text(((CW - w2) / 2, CH - 92), sub, font=f2, fill=(255, 255, 255))
    return out


def white_image(cover, style="classic", song="", artist="", album="", dur="", p=None,
                transparent=False, width=1181, tag=""):
    """电商白底 / 透明底商品图：白底 + 原仓库贴片 + 内腔播放卡。"""
    p = p or {}
    W = _clamp(_int(width, 1181), 400, 2400)
    H = W
    base = (0, 0, 0, 0) if transparent else (255, 255, 255, 255)
    canvas = Image.new("RGBA", (W, H), base)
    ov, (px, py), inner = _geometry(style, W, H, 0.82)
    x0, y0, x1, y1 = inner
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    if x1 > x0 and y1 > y0:
        card = _inner_card(cover, song, artist, album, dur, p, (x1 - x0, y1 - y0))
        canvas.paste(card, (x0, y0))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.paste(ov, (px, py))
    canvas = Image.alpha_composite(canvas, layer)
    if tag and tag not in ("方形", "默认") and not transparent:
        d = ImageDraw.Draw(canvas, "RGBA")
        f = _font(max(14, round(W * 0.032)), False)
        tw = d.textlength(str(tag), font=f)
        d.rounded_rectangle([W - tw - 46, H - 62, W - 16, H - 16], radius=8,
                            fill=(255, 255, 255, 210), outline=(210, 210, 210, 255), width=2)
        d.text((W - tw - 31, H - 57), str(tag), font=f, fill=(110, 110, 110, 255))
    return canvas

# -*- coding: utf-8 -*-
"""歌曲周边合成 —— 源自 GitHub music-merch-studio 的商品图功能。

几何基准（实测自原仓库 assets/keychain 贴片，非估算）：
    长方形     贴片 keychain_overlay.png 1920×1920
              外轮廓 bbox (688,232)-(1233,1687)，内腔 (732,873)-(1184,1627) → 453×755
    八角形     贴片 clear_square_ring_overlay.png 1254×1254
              外轮廓 bbox (41,21)-(1193,1227)，内腔 (445,555)-(809,1108) → 364×553

合成方式（与原 tools/make_keychain_shop.py 一致）：
    画布 → 内腔贴封面卡（略放大 bleed 藏进卡套边框）→ 亚克力贴片（内腔透明）盖上。

另提供「黑胶播放界面」与拼版输出，参数由制作页表单传入并真实生效。
"""
import os
import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from . import kc_scene

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KC_DIR = os.path.join(BASE, "static", "keychain")
FONTS = os.path.join(BASE, "fonts")
CJK_BOLD = os.path.join(FONTS, "NotoSansCJKsc-Bold.otf")
CJK_REG = os.path.join(FONTS, "NotoSansCJKsc.otf")

CARD_BLEED = 4          # 卡片四周多出的像素，藏进卡套边框底下
BG_BLUR = 20            # 场景图背景模糊半径（与原仓库一致）

# 款式名按用户要求：长条透明款→长方形，透明方形圆环款→八角形
STYLES = {
    "classic": {
        "label": "长方形",
        "overlay": "keychain_overlay.png",
        "bbox": (688, 232, 1233, 1687),
        "inner": (732, 873, 1184, 1627),
        "canvas_h": 2000, "pad": 0.060,
    },
    "square_ring": {
        "label": "八角形",
        "overlay": "clear_square_ring_overlay.png",
        "bbox": (41, 21, 1193, 1227),
        "inner": (445, 555, 809, 1108),
        "canvas_h": 1600, "pad": 0.080,
    },
}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _font(size, bold=True):
    try:
        return ImageFont.truetype(CJK_BOLD if bold else CJK_REG, max(8, int(size)))
    except Exception:
        return ImageFont.load_default()


def _spec(style):
    return STYLES.get(style, STYLES["classic"])


def _load_overlay_trimmed(style):
    """读贴片并裁到外轮廓，去掉四周透明区。"""
    sp = _spec(style)
    x0, y0, x1, y1 = sp["bbox"]
    with Image.open(os.path.join(KC_DIR, sp["overlay"])) as src:
        return src.convert("RGBA").crop((x0, y0, x1 + 1, y1 + 1))


def _canvas_size(style):
    sp = _spec(style)
    x0, y0, x1, y1 = sp["bbox"]
    ow, oh = x1 - x0 + 1, y1 - y0 + 1
    h = sp["canvas_h"]
    pad = sp["pad"]
    target_h = round(h * (1 - 2 * pad))
    w = round(ow * target_h / oh / (1 - 2 * pad))
    return w, h


def _make_unit(cover, style, transparent=False, tag=""):
    """一只钥匙扣的商品图（RGBA，白底或透明底）。"""
    sp = _spec(style)
    x0, y0, x1, y1 = sp["bbox"]
    ix0, iy0, ix1, iy1 = sp["inner"]
    ow, oh = x1 - x0 + 1, y1 - y0 + 1
    iw, ih = ix1 - ix0 + 1, iy1 - iy0 + 1
    CW, CH = _canvas_size(style)
    pad = sp["pad"]
    target_h = round(CH * (1 - 2 * pad))
    scale = target_h / oh

    uw = round(ow * scale)
    ux = (CW - uw) // 2
    uy = round(CH * pad)

    base_bg = (0, 0, 0, 0) if transparent else (255, 255, 255, 255)
    base = Image.new("RGBA", (CW, CH), base_bg)

    # 内卡：封面居中裁切填满内腔（与原仓库口径一致：填满、不拉伸、避免色带）
    card_w = round(iw * scale) + CARD_BLEED
    card_h = round(ih * scale) + CARD_BLEED
    card_x = ux + round((ix0 - x0) * scale) - CARD_BLEED // 2
    card_y = uy + round((iy0 - y0) * scale) - CARD_BLEED // 2
    rgb = cover.convert("RGB")
    card = Image.new("RGB", (card_w, card_h), rgb.getpixel((0, rgb.height - 1)))
    card.paste(ImageOps.fit(rgb, (card_w, card_h), Image.LANCZOS), (0, 0))
    base.paste(card, (card_x, card_y))

    # 亚克力贴片盖上面（内腔透明，卡片正好透出来）
    base.alpha_composite(_load_overlay_trimmed(style).resize((uw, target_h), Image.LANCZOS), (ux, uy))

    # 电商画布角标：选了具体平台才打标，默认「方形」保持画面干净
    if tag and tag not in ("方形", "默认"):
        d = ImageDraw.Draw(base, "RGBA")
        f = _font(max(14, round(CW * 0.032)), bold=False)
        t = str(tag)
        w = d.textlength(t, font=f)
        d.rounded_rectangle([CW - w - 46, CH - 62, CW - 16, CH - 16],
                            radius=8, fill=(255, 255, 255, 210), outline=(210, 210, 210, 255), width=2)
        d.text((CW - w - 31, CH - 57), t, font=f, fill=(110, 110, 110, 255))
    return base


def _resize_width(im, w):
    """按主尺寸缩放输出图，等比，限制最大高度避免超大文件。"""
    w = _clamp(_int(w, 1181), 400, 2400)
    h = round(im.height * w / im.width)
    if h > 5000:
        h = 5000
        w = round(im.width * h / im.height)
    return im.resize((w, h), Image.LANCZOS) if (w, h) != im.size else im


def make_white(cover, style="classic"):
    """兼容旧调用：电商白底图，统一走新版四步合成。"""
    return kc_scene.white_image(cover, style)


def make_scene_legacy(cover, style="classic", song="", artist=""):
    """旧版场景商品图（保留备查，正式输出不再使用）。"""
    unit = _make_unit(cover, style)

    cw, ch = 1920, 1920
    bg = cover.convert("RGB").resize((cw, ch), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(BG_BLUR))
    veil = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(veil).rectangle([0, 0, cw, ch], outline=255, fill=0)
    overlay = Image.new("RGB", (cw, ch), (12, 12, 16))
    bg = Image.composite(overlay, bg, veil.filter(ImageFilter.GaussianBlur(120)).point(lambda v: v // 2))

    scene = bg.convert("RGBA")
    uw, uh = unit.size
    scale = (cw * 0.62) / uh
    uw2, uh2 = round(uw * scale), round(uh * scale)
    unit2 = unit.resize((uw2, uh2), Image.LANCZOS)
    ux, uy = (cw - uw2) // 2, (ch - uh2) // 2 + 30

    shadow = Image.new("RGBA", (uw2 + 120, uh2 + 120), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([60, 90, uw2 + 60, uh2 + 60], radius=40, fill=(0, 0, 0, 110))
    scene.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(26)), (ux - 60, uy - 60))
    scene.alpha_composite(unit2, (ux, uy))

    scene = scene.convert("RGB")
    d = ImageDraw.Draw(scene)
    if song:
        f = ImageFont.truetype(CJK_BOLD, 74)
        text = song if len(song) <= 16 else song[:15] + "…"
        w = d.textlength(text, font=f)
        tx, ty = (cw - w) / 2, 74
        d.text((tx + 3, ty + 3), text, font=f, fill=(0, 0, 0, 160))
        d.text((tx, ty), text, font=f, fill=(255, 255, 255))
    if artist:
        f2 = ImageFont.truetype(CJK_BOLD, 40)
        sub = artist + " · 拾音乐坊 歌曲钥匙扣"
        w2 = d.textlength(sub, font=f2)
        d.text(((cw - w2) / 2, ch - 110), sub, font=f2, fill=(255, 255, 255))
    return scene


def _cur_time(dur):
    """按进度 32% 推算当前播放时间。"""
    try:
        mm, ss = (dur or "04:29").split(":")
        total = int(mm) * 60 + int(ss)
        cur = round(total * 0.32)
        return "%02d:%02d" % (cur // 60, cur % 60)
    except Exception:
        return "01:26"


def make_vinyl(cover, song="", artist="", album="", dur="", p=None):
    """黑胶播放界面（网易云风格竖版）。表单参数全部真实生效。返回 RGB。"""
    p = p or {}
    W = _clamp(_int(p.get("vinyl_w"), 1200), 600, 1800)
    H = round(W * 1.92)
    s = W / 1200.0

    def R(v):
        return max(1, round(v * s))

    def F(sz, bold=True):
        return _font(R(sz), bold)

    # 背景：封面模糊铺满 + 压暗
    bg = ImageOps.fit(cover.convert("RGB"), (W, H), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(R(28)))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (18, 20, 24)), 0.62)
    im = bg.convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")

    # 状态栏
    d.text((R(46), R(24)), "15:28", font=F(32), fill=(255, 255, 255, 235))
    d.rounded_rectangle([W - R(152), R(30), W - R(58), R(58)], radius=R(7),
                        outline=(255, 255, 255, 200), width=R(3))
    d.rounded_rectangle([W - R(146), R(35), W - R(92), R(53)], radius=R(4), fill=(255, 255, 255, 220))
    for k in range(4):
        x = W - R(210) + k * R(16)
        d.rounded_rectangle([x, R(52) - k * R(7), x + R(9), R(58)], radius=R(2),
                            fill=(255, 255, 255, 210))

    # 导航栏
    title = str(p.get("list_title") or "我喜欢的音乐")
    d.text((R(40), R(96)), "<", font=F(52), fill=(255, 255, 255, 235))
    d.text((R(108), R(104)), title[:12], font=F(38), fill=(255, 255, 255, 240))
    d.text((W - R(78), R(100)), "...", font=F(40), fill=(255, 255, 255, 210))

    # 黑胶唱片
    cx, cy, rad = W // 2, R(760), R(430)
    d.ellipse([cx - rad - R(18), cy - rad - R(18), cx + rad + R(18), cy + rad + R(18)],
              fill=(24, 26, 30, 255))
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(16, 16, 18, 255))
    for k in range(1, 9):
        r = rad - R(20) - k * R(24)
        if r > R(262):
            g = 58 + k * 9
            d.ellipse([cx - r, cy - r, cx + r, cy + r],
                      outline=(g, g + 2, g + 8, 255), width=R(2))
    d.arc([cx - rad, cy - rad, cx + rad, cy + rad], 198, 288,
          fill=(150, 156, 166, 255), width=R(14))
    d.arc([cx - rad, cy - rad, cx + rad, cy + rad], 18, 108,
          fill=(96, 102, 110, 255), width=R(10))

    # 中心圆形封面
    cr = R(250)
    cimg = ImageOps.fit(cover.convert("RGB"), (cr * 2, cr * 2), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (cr * 2, cr * 2), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, cr * 2 - 1, cr * 2 - 1], fill=255)
    cimg.putalpha(mask)
    im.alpha_composite(cimg, (cx - cr, cy - cr))
    d.ellipse([cx - R(16), cy - R(16), cx + R(16), cy + R(16)], fill=(22, 22, 24, 255))

    # 唱臂
    px, py = cx + rad + R(48), R(250)
    d.ellipse([px - R(36), py - R(36), px + R(36), py + R(36)], fill=(208, 210, 214, 255))
    d.line([px, py, cx + R(150), cy - rad + R(80)], fill=(208, 210, 214, 255), width=R(14))
    d.ellipse([cx + R(126), cy - rad + R(56), cx + R(174), cy - rad + R(104)],
              fill=(232, 234, 238, 255))

    # 歌名 / 歌手
    ny = R(1300)
    name = song or "未命名歌曲"
    if len(name) > 18:
        name = name[:17] + "…"
    f = F(62)
    nw = d.textlength(name, font=f)
    nx = (W - nw) / 2
    d.text((nx, ny), name, font=f, fill=(255, 255, 255, 250))
    if p.get("vip"):
        vx, vy = nx + nw + R(16), ny + R(14)
        d.rounded_rectangle([vx, vy, vx + R(88), vy + R(44)], radius=R(8),
                            fill=(214, 178, 106, 240))
        d.text((vx + R(12), vy + R(6)), "VIP", font=F(26), fill=(48, 38, 20, 255))

    sub = (artist or "未知歌手") + (" · " + album if album else "")
    f2 = F(34, False)
    sw = d.textlength(sub, font=f2)
    sx = (W - sw) / 2
    d.text((sx, ny + R(92)), sub[:30], font=f2, fill=(226, 226, 232, 225))
    if p.get("follow"):
        bw, bh = R(126), R(48)
        bx, by = sx + sw + R(18), ny + R(86)
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2,
                            outline=(255, 255, 255, 170), width=R(2))
        d.text((bx + R(20), by + R(8)), "+ 关注", font=F(26, False), fill=(255, 255, 255, 235))

    # 进度条
    py2 = R(1530)
    x0, x1 = R(120), W - R(120)
    d.rounded_rectangle([x0, py2, x1, py2 + R(6)], radius=R(3), fill=(116, 120, 126, 255))
    prog = x0 + (x1 - x0) * 0.32
    d.rounded_rectangle([x0, py2, prog, py2 + R(6)], radius=R(3), fill=(255, 255, 255, 235))
    d.ellipse([prog - R(12), py2 - R(9), prog + R(12), py2 + R(15)], fill=(255, 255, 255, 255))
    f3 = F(25, False)
    d.text((x0, py2 + R(22)), _cur_time(dur), font=f3, fill=(255, 255, 255, 175))
    dt = str(dur or "04:29")
    tw = d.textlength(dt, font=f3)
    d.text((x1 - tw, py2 + R(22)), dt, font=f3, fill=(255, 255, 255, 175))

    # 播放控制
    bcy = R(1740)
    br = R(86)
    d.text((R(78), bcy - R(14)), str(p.get("play_mode") or "列表循环")[:4],
           font=F(25, False), fill=(255, 255, 255, 180))
    d.ellipse([W // 2 - br, bcy - br, W // 2 + br, bcy + br], fill=(255, 255, 255, 240))
    t = R(32)
    d.polygon([(W // 2 - t * 0.55, bcy - t), (W // 2 - t * 0.55, bcy + t),
               (W // 2 + t, bcy)], fill=(28, 28, 30, 255))
    for off, sign in ((-R(240), -1), (R(240), 1)):
        bx = W // 2 + off
        tt = R(34)
        if sign > 0:
            d.polygon([(bx - tt, bcy - tt), (bx - tt, bcy + tt), (bx + tt, bcy)],
                      fill=(255, 255, 255, 235))
            d.line([bx + tt + R(6), bcy - tt, bx + tt + R(6), bcy + tt],
                   fill=(255, 255, 255, 235), width=R(6))
        else:
            d.polygon([(bx + tt, bcy - tt), (bx + tt, bcy + tt), (bx - tt, bcy)],
                      fill=(255, 255, 255, 235))
            d.line([bx - tt - R(6), bcy - tt, bx - tt - R(6), bcy + tt],
                   fill=(255, 255, 255, 235), width=R(6))
    d.text((W - R(210), bcy - R(14)), "收藏", font=F(25, False), fill=(255, 255, 255, 180))
    d.text((W - R(110), bcy - R(14)), "评论", font=F(25, False), fill=(255, 255, 255, 180))

    # 底部信息卡：热度 / 在线人数 / auto
    by = R(1950)
    d.rounded_rectangle([R(70), by, W - R(70), by + R(230)], radius=R(24),
                        fill=(44, 48, 54, 255), outline=(96, 100, 106, 255), width=R(2))
    cols = [("热度 / 评论", str(p.get("hot_text") or "999w+")),
            ("在线", str(p.get("online_text") or "999+人")),
            ("品质", str(p.get("auto_text") or "auto"))]
    for i, (lab, val) in enumerate(cols):
        px2 = R(110) + i * (W - R(220)) / 3
        d.text((px2, by + R(28)), lab, font=F(26, False), fill=(186, 190, 198, 255))
        d.text((px2, by + R(82)), val[:10], font=F(42), fill=(255, 255, 255, 255))
    d.text((R(76), H - R(76)), "拾音乐坊 · SONG / PRODUCT MAKER",
           font=F(24, False), fill=(255, 255, 255, 130))
    return im.convert("RGB")


def make_contact(images, density=32):
    """单品拼版总览：按横向密度把商品图排成网格。"""
    if not images:
        return Image.new("RGB", (800, 600), (255, 255, 255))
    n = _clamp(_int(density, 32), 4, 64)
    cols = 8 if n >= 24 else (6 if n >= 12 else 4)
    rows = math.ceil(n / cols)
    src = images[0]
    cw = 160
    ch = min(560, round(cw * src.height / src.width))
    pad, gap = 24, 12
    W, H = pad * 2 + cols * cw + (cols - 1) * gap, pad * 2 + rows * ch + (rows - 1) * gap
    out = Image.new("RGB", (W, H), (247, 246, 242))
    d = ImageDraw.Draw(out)
    for i in range(n):
        r, c = divmod(i, cols)
        x, y = pad + c * (cw + gap), pad + r * (ch + gap)
        unit = images[i % len(images)].convert("RGB")
        th = ImageOps.contain(unit, (cw - 8, ch - 26), Image.LANCZOS)
        out.paste(th, (x + (cw - th.width) // 2, y + 4))
        d.rectangle([x, y, x + cw, y + ch], outline=(214, 214, 208), width=1)
        d.text((x + 6, y + ch - 20), "%02d" % (i + 1), font=_font(14, False), fill=(120, 120, 116))
    return out


def make_a4(vinyl):
    """播放界面 A4 四拼拼版。"""
    W, H = 1400, 1980
    out = Image.new("RGB", (W, H), (250, 249, 245))
    d = ImageDraw.Draw(out)
    d.text((70, 46), "播放界面 · A4 四拼拼版", font=_font(46), fill=(38, 62, 50))
    d.text((70, 106), "拾音乐坊 SONG / PRODUCT MAKER", font=_font(24, False), fill=(130, 140, 132))
    m, top, gap = 70, 160, 30
    cw = (W - 2 * m - gap) // 2
    ch = (H - top - m - gap) // 2
    v = vinyl.convert("RGB")
    for i in range(4):
        th = ImageOps.contain(v, (cw, ch), Image.LANCZOS)
        x = m + (i % 2) * (cw + gap) + (cw - th.width) // 2
        y = top + (i // 2) * (ch + gap) + (ch - th.height) // 2
        out.paste(th, (x, y))
        d.rectangle([x, y, x + th.width, y + th.height], outline=(204, 204, 198), width=2)
    return out


def make_scene(cover, style="classic", song="", artist="", album="", dur="", p=None):
    """钥匙扣商品图：新版四步合成（模糊封面 → 白框封面 → 模板 → 内腔播放卡）。"""
    return kc_scene.scene_image(cover, style, song, artist, album, dur, p)


def generate(cover, style="classic", song="", artist=""):
    """兼容旧调用：白底电商图 + 商品图，均走新版合成。"""
    return {"white": kc_scene.white_image(cover, style),
            "scene": kc_scene.scene_image(cover, style, song, artist)}


def generate_all(cover, styles, outputs, params, song="", artist="", album="", dur=""):
    """按制作页勾选项产出全部商品图。

    返回 [(分组, 标签, key, PIL图, 是否透明底), ...]
    """
    p = params or {}
    styles = [s for s in (styles or ["classic"]) if s in STYLES][:2] or ["classic"]
    outputs = [o for o in (outputs or ["scene", "white", "vinyl"]) if o in ("scene", "white", "vinyl")]
    bg_mode = str(p.get("bg") or "两种")
    main_w = _int(p.get("main_w"), 1181)
    canvas_tag = str(p.get("canvas") or "方形")
    density = _int(p.get("density"), 32)

    items = []
    whites = []
    for st in styles:
        lab = STYLES[st]["label"]
        # 白底单品图恒生成一份，供拼版总览使用；是否交付由输出勾选项决定
        unit = kc_scene.white_image(cover, st, song, artist, album, dur, p,
                                    transparent=False, width=main_w, tag=canvas_tag)
        whites.append(unit)
        if "white" in outputs:
            if bg_mode in ("白底", "两种"):
                items.append(("电商白底图", lab + " · 白底", "white_" + st, unit, False))
            if bg_mode in ("透明", "两种"):
                trans = kc_scene.white_image(cover, st, song, artist, album, dur, p,
                                             transparent=True, width=main_w, tag=canvas_tag)
                items.append(("电商白底图", lab + " · 透明底", "white_" + st + "_trans", trans, True))
        if "scene" in outputs:
            items.append(("钥匙扣商品图", lab, "scene_" + st,
                          kc_scene.scene_image(cover, st, song, artist, album, dur, p), False))

    vinyl = None
    if "vinyl" in outputs:
        vinyl = make_vinyl(cover, song, artist, album, dur, p)
        items.append(("黑胶播放界面", str(_int(p.get("vinyl_w"), 1200)) + "px", "vinyl", vinyl, False))

    if p.get("extra_contact") and whites:
        items.append(("附加输出", "单品拼版总览 · " + str(_clamp(density, 4, 64)) + " 张",
                      "contact", make_contact(whites, density), False))
    if p.get("extra_a4") and vinyl is not None:
        items.append(("附加输出", "播放界面 A4 四拼拼版", "a4", make_a4(vinyl), False))
    return items

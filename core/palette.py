# -*- coding: utf-8 -*-
"""从封面提取主色，并派生整套素材的统一色板（暗→亮色调渐变）。"""
import numpy as np
from PIL import Image
from colorsys import rgb_to_hsv, hsv_to_rgb


def _hsv(h, s, v):
    r, g, b = hsv_to_rgb(h, s, v)
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def extract_palette(cover_img, samples=200):
    """封面 → 6 色色板（deep/brown/amber/gold/cream/ink）。

    策略：对封面做中位切分量化，取出现频率最高、且非极暗/极亮的主色作为色相基准，
    再沿同一色相构造一条由暗到亮的色调渐变，保证整套素材视觉连续。
    """
    img = cover_img.convert("RGB").resize((samples, samples))
    q = img.quantize(colors=14, method=Image.MEDIANCUT)
    pal = q.getpalette()[:14 * 3]
    counts = q.getcolors(14)  # list of (count, idx)
    counts.sort(reverse=True)

    dom = None
    for _, idx in counts:
        r, g, b = pal[idx * 3:idx * 3 + 3]
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        if 28 < lum < 232:        # 跳过纯黑/纯白/近黑近白
            dom = (r, g, b)
            break
    if dom is None:               # 极端封面兜底：取最高频色
        _, idx = counts[0]
        dom = tuple(pal[idx * 3:idx * 3 + 3])

    h, s, v = rgb_to_hsv(dom[0] / 255.0, dom[1] / 255.0, dom[2] / 255.0)
    s = float(min(1.0, max(0.30, s)))   # 保底一定饱和度，避免灰调
    # 若主色本身很亮（高 v），整体压暗一点，避免背景过曝
    vbase = min(v, 0.78) if v > 0.55 else v

    palette = {
        "deep":  _hsv(h, s * 0.85, 0.10),
        "brown": _hsv(h, s * 0.88, 0.26 + 0.10 * vbase),
        "amber": _hsv(h, s * 0.92, 0.46 + 0.10 * vbase),
        "gold":  _hsv(h, s * 0.78, 0.72),
        "cream": _hsv(h, s * 0.32, 0.93),
        "ink":   _hsv(h, s * 0.72, 0.16),
    }
    return palette


def _mix(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def ramp_deep(p):
    """暗调背景渐变（盘面/侧封）。"""
    return [(0.0, p["deep"]), (0.35, p["brown"]), (0.62, p["amber"]),
            (0.85, p["gold"]), (1.0, p["cream"])]


def ramp_light(p):
    """亮调背景渐变（封面背面/封底）——整体保持浅色，确保深色文字可读。"""
    c = p["cream"]
    return [(0.0, _mix(p["gold"], c, 0.55)), (0.4, c),
            (0.72, _mix(c, (255, 250, 242), 0.6)), (1.0, (253, 249, 242))]


def ramp_mid(p):
    """中调背景渐变（内盘底）。"""
    return [(0.0, p["brown"]), (0.4, p["amber"]), (0.72, p["gold"]),
            (1.0, p["cream"])]


def to_hex(p):
    return {k: "#%02X%02X%02X" % v for k, v in p.items()}


def swatches(p):
    """返回前端展示用的色块列表（hex + 名称）。"""
    order = [("deep", "深"), ("brown", "褐"), ("amber", "琥珀"),
             ("gold", "金"), ("cream", "奶白"), ("ink", "墨")]
    return [{"key": k, "name": n, "hex": "#%02X%02X%02X" % p[k]} for k, n in order]

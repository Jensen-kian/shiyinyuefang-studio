# -*- coding: utf-8 -*-
"""EAN-13 编码 → UPC-A 风格细条渲染（复刻样张：细窄条、警戒条下延、数字分组带间距）。"""
from PIL import Image, ImageDraw, ImageFont
import os

FONTS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")
_deja = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


# EAN-13 编码表（与官方标准一致）
LEFT_PATTERN = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]  # 占位，下面用查表
L_CODES = {
    "0": "0001101", "1": "0011001", "2": "0010011", "3": "0111101", "4": "0100011",
    "5": "0110001", "6": "0101111", "7": "0111011", "8": "0110111", "9": "0001011",
}
G_CODES = {
    "0": "0100111", "1": "0110011", "2": "0011011", "3": "0100001", "4": "0011101",
    "5": "0111001", "6": "0000101", "7": "0010001", "8": "0001001", "9": "0010111",
}
R_CODES = {
    "0": "1110010", "1": "1100110", "2": "1101100", "3": "1000010", "4": "1011100",
    "5": "1001110", "6": "1010000", "7": "1000100", "8": "1001000", "9": "1110100",
}
# 首位决定左侧 6 位的编码奇偶组合
FIRST_PARITY = {
    "0": "LLLLLL", "1": "LLGLGG", "2": "LLGGLG", "3": "LLGGGL", "4": "LGLLGG",
    "5": "LGGLLG", "6": "LGGGLL", "7": "LGLGLG", "8": "LGLGGL", "9": "LGGLGL",
}
EDGE = "101"
MIDDLE = "01010"


def ean13_bits(num13):
    assert len(num13) == 13 and num13.isdigit()
    bits = EDGE
    parity = FIRST_PARITY[num13[0]]
    for d, p in zip(num13[1:7], parity):
        bits += (L_CODES if p == "L" else G_CODES)[d]
    bits += MIDDLE
    for d in num13[7:]:
        bits += R_CODES[d]
    return bits + EDGE


def build_barcode(num13, target_w_mm, font_size=48):
    """渲染 UPC-A 风格条形码，缩放到 target_w_mm 像素宽，返回 PIL Image(RGB)。"""
    bits = ean13_bits(num13)
    mw = 5                       # 每模块像素（细条）
    bar_h = 100                  # 主条高
    ext = 38                     # 警戒条下延
    fd = ImageFont.truetype(_deja, font_size)
    digit_h = fd.getbbox("0")[3] - fd.getbbox("0")[1]
    pad_m = 6
    Wc = (95 + pad_m * 2) * mw
    digit_y = bar_h + ext - digit_h
    Hc = digit_y + digit_h + 14
    img = Image.new("RGB", (Wc, Hc), (255, 255, 255))
    d = ImageDraw.Draw(img)
    guards = set(range(0, 3)) | set(range(45, 50)) | set(range(92, 95))
    for i, b in enumerate(bits):
        if b == "1":
            h = bar_h + (ext if i in guards else 0)
            d.rectangle([pad_m * mw + i * mw, 0, pad_m * mw + (i + 1) * mw - 1, h],
                        fill=(18, 14, 10))
    # 数字：首尾在警戒条外侧，其余分组居中于各自半区正下方
    centers = [-4.5] + [3 + 7 * i + 3.5 for i in range(6)] + \
              [50 + 7 * i + 3.5 for i in range(6)] + [99.5]
    for ch, cm in zip(num13, centers):
        d.text((pad_m * mw + cm * mw, digit_y), ch, font=fd,
               fill=(18, 14, 10), anchor="ma")
    return img


if __name__ == "__main__":
    b = build_barcode("8804775454394", 200)
    b.save("/tmp/bc_test.png")
    print("ok", b.size)

"""合成音频后处理：去爆音（段间采样跳变）+ 可选轻度谱门降噪。

IndexTTS 每次推理在 segment 边界插入静音，拼接处常出现单采样级跳变（听感是「咔」的一声），
22.05 kHz 的输出在上限附近也会带一点宽带噪声。这里两步都很轻，尽量不改音色：

  * declick：找出 |Δsample| > th 的位置，用 3 ms 线性插值跨过去（默认开，th=0.5）
  * denoise：noisereduce 的谱门（stationary=False），prop_decrease 控制强度（默认 0.5，0=关闭）

用法（就地清理已有文件）：
    index-tts/.venv/bin/python example/audio_clean.py audiobook/0001-0020.wav --inplace
"""

import argparse
import os
import sys

import numpy as np


def declick(y, sr, th=0.5, ms=3.0):
    """跨过单采样跳变，消除拼接处的「咔哒」。"""
    y = np.asarray(y).copy()
    jumps = np.where(np.abs(np.diff(y)) > th)[0]
    if len(jumps) == 0:
        return y, 0
    w = max(1, int(sr * ms / 1000))
    for i in jumps:
        a, b = max(0, i - w), min(len(y) - 1, i + w)
        if b - a > 1:
            y[a:b + 1] = np.linspace(y[a], y[b], b - a + 1)
    return y, int(len(jumps))


def denoise(y, sr, prop=0.5):
    if prop <= 0:
        return y
    import noisereduce as nr

    return nr.reduce_noise(y=y, sr=sr, stationary=False,
                           prop_decrease=float(prop), n_fft=1024, win_length=1024)


def clean(y, sr, declick_th=0.5, denoise_prop=0.5):
    y, n = declick(y, sr, th=declick_th)
    return denoise(y, sr, prop=denoise_prop), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--declick-th", type=float, default=0.5)
    ap.add_argument("--denoise", type=float, default=0.5, help="0 表示只去爆音")
    ap.add_argument("--inplace", action="store_true")
    args = ap.parse_args()

    import soundfile as sf

    for path in args.files:
        y, sr = sf.read(path, dtype="float32")
        if y.ndim > 1:
            y = y.mean(1)
        out, n = clean(y, sr, args.declick_th, args.denoise)
        dst = path if args.inplace else os.path.splitext(path)[0] + "_clean.wav"
        sf.write(dst, out, sr)
        print(f"{path}: jumps={n} peak={np.abs(out).max():.2f} -> {dst}")


if __name__ == "__main__":
    main()

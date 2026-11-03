"""参考音频与合成文本的唯一来源，两个脚本共用，避免多处复制。"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")

# 参考音频：取自 BV1w64y1j7HT 的 343.86–350.71 s（6.85 s 纯语音）
REF_7S = os.path.join(ASSETS, "ref_vertin_7s.wav")
# 同段素材的 20 s 版本：IndexTTS 没有 3–10 s 限制，也用作相似度评分基准
REF_20S = os.path.join(ASSETS, "ref_vertin_20s.wav")

# 参考音频的逐字原文（whisper 转写 + 与剧情文本核对）
PROMPT_TEXT = ("It's not working. I've tried different ways, but the tempests blocked "
               "every signal I sent for help. Wait, there might be another way.")

TEXT_EN = ("The rain has stopped. For now, at least. We should keep moving. "
           "There is still a long way ahead of us.")
TEXT_ZH = "雨停了。至少现在是。我们该继续走了。前面的路还很长。"

JOBS = (("en", TEXT_EN), ("zh", TEXT_ZH))

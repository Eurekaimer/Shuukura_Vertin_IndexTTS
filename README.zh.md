# Shuukura_Vertin_IndexTTS — 中文说明

用 **IndexTTS-2.5** 克隆《重返未来：1999》维尔汀的声音，把中文 EPUB 与抓取的英文小说
转成有声书。完整英文说明见 [README.md](README.md)。

## 目录

```
books/shuukura-zh/   book.json + source/*.epub       中文来源
books/shuukura-en/   book.json + parts/ + chapters/  英文抓取结果（不入库）
tools/               全部脚本：books / scrape_parts / tts_book / make_plan …
assets/              ref_vertin_7s.wav, ref_vertin_20s.wav
audiobook/           输出与断点检查点（不入库）
example/             试听样本（含 en_preview/ 英文试听）
```

## 环境

```bash
uv sync                                    # 抓取器依赖（requests）
cd index-tts && uv sync --python 3.10      # 推理环境；不要加 --all-extras
```

## 用法

```bash
# 中文：续跑整本，20 章一个文件
./bin/vertin-read

# 英文：抓两章（可续跑，重复运行会跳过已下载的 part）
uv run python tools/scrape_parts.py --chapters 1-2

# 英文：每章一个文件，输出到 example/en_preview/
index-tts/.venv/bin/python tools/tts_book.py \
  --book books/shuukura-en --out-dir example/en_preview --per-file 1 \
  --format flac --smooth --device cuda:0

# 导出逐章断句计划（检查用）
index-tts/.venv/bin/python tools/make_plan.py --book books/shuukura-zh
```

输出命名为 `ch0001.flac`、`ch0002.flac`；每章先写检查点，校验 sha256 后才合并，
中断后重跑即可续。换书、换参考音频、改断句或生成参数都会启用新的检查点命名空间。

英文试听：`example/en_preview/ch0001.flac`、`ch0002.flac`。

## 参数

* 中文：`unit_chars=70`，`join_lines=""`；
* 英文：`unit_chars=140`，`join_lines=" "`，句末 `.!?;…`，小句 `,;:`；
* 停顿：句末 0.35 s，小句末 0.18 s，章间 1.0 s；
* 显存峰值约 5.9 GB / 7.6 GB，只能单进程推理；`--device cpu` 可跑但慢约 20 倍。

## 来源

* 英文文本：Ave Lilium 翻译
  <https://avelilium.com/story-about-buying-my-classmate-once-a-week/>
  （章节正文托管于 <https://amawashigroup.wordpress.com/>）
* 中文文本：《一周一次买下同班同学的那些事》羽田宇佐，粉丝翻译 EPUB
* 参考声音：B 站 BV1w64y1j7HT，343.86–350.71 s
* 模型：[IndexTeam/IndexTTS-2.5](https://huggingface.co/IndexTeam/IndexTTS-2.5)

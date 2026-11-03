# Shuukura_Vertin_IndexTTS — 中文说明

用 **IndexTTS-2.5** 克隆《重返未来：1999》维尔汀的声音，把抓取的英文小说转成有声书。
完整英文说明见 [README.md](README.md)。

## 推荐英文版本

**请使用英文版**（`books/shuukura-en`）：同一套维尔汀检查点读英文翻译时断词和停顿自然。
中文 EPUB 仅保留作对照——英文参考音读中文会有明显的「辣条音」质感，因此不再生成中文
有声书，只保留 `example/` 下的中文试听样本。

## 目录

```
books/shuukura-zh/   book.json + source/*.epub       中文来源（仅对照）
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
# 英文：抓取全部章节（可续跑，重复运行会跳过已下载的 part）
uv run python tools/scrape_parts.py --chapters all

# 英文：整本推理，默认每章一个文件，输出 audiobook/shuukura-en/
vertin-read

# 导出逐章断句计划（检查用）
index-tts/.venv/bin/python tools/make_plan.py --book books/shuukura-en
```

输出命名为 `ch0001.flac`、`ch0002.flac`：每个 web chapter 一个文件，音频内部按
`parts/` 顺序拼接，part 之间插入 1.2 s 静音。每章先写检查点，校验 sha256 后才合并；
中断或重启后重跑即可续，最多损失当前正在生成的那一章。

中文如需重新生成（不推荐，会有辣条音）：

```bash
vertin-read --book "$PWD/books/shuukura-zh" --out-dir "$PWD/audiobook/shuukura-zh" \
  --per-file 1
```

## 参数

* 英文：`unit_chars=140`，`join_lines=" "`，句末 `.!?;…`，小句 `,;:`；
* 英文停顿：句末 0.45 s，小句末 0.22 s，段末 0.75 s，part 之间 1.2 s，章间 1.0 s；
* 中文：`unit_chars=70`，`join_lines=""`，句末 0.35 s、小句末 0.18 s；
* 朗读润色：去掉网页/页脚残留与装饰行，括号式 en/em dash 改为逗号，行首破折号提示删除；
* 显存峰值约 5.9 GB / 7.6 GB，只能单进程推理；`--device cpu` 可跑但慢约 20 倍。

## 来源

* 英文文本：Ave Lilium 翻译
  <https://avelilium.com/story-about-buying-my-classmate-once-a-week/>
  （章节正文托管于 <https://amawashigroup.wordpress.com/>）
* 中文文本：《一周一次买下同班同学的那些事》羽田宇佐，粉丝翻译 EPUB
* 参考声音：B 站 BV1w64y1j7HT，343.86–350.71 s
* 模型：[IndexTeam/IndexTTS-2.5](https://huggingface.co/IndexTeam/IndexTTS-2.5)

# PDF 翻译 Skill

英文 PDF → 中文译文 PDF + 英文在左、中文在右的内容块对齐 PDF。

v2 通过当前助手会话翻译，以本地 PyMuPDF 脚本提取和排版，无需单独的翻译 API。保留整段与段内粗斜体，支持本地图片 OCR 和 PDF 内嵌附件翻译。专名、人名按 `中文（English）` 展开；保存问题、裁决、术语和续跑状态。

技能入口：[skills/pdf-translate/SKILL.md](skills/pdf-translate/SKILL.md)。命令和 JSON 格式见 [工作流](skills/pdf-translate/references/workflow.md)。已确认需求见 [v1 规划](docs/v1-plan.md)。

发布版本：[v2.0.0 下载](https://github.com/xjunrao-ux/PaperTranslate/releases/tag/v2.0.0)，包含技能安装包与 SHA-256 校验文件；详情见 [更新说明](docs/releases/v2.0.0.md)。

## 安装依赖

使用 Python 3.10+ 创建虚拟环境，再安装技能依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r skills\pdf-translate\requirements.txt
.\.venv\Scripts\python.exe skills\pdf-translate\scripts\pdf_translate.py doctor
```

也可使用 uv。本项目验证时复用了 Codex 自带 Python，通过 uv 在 `.venv` 中安装了固定版本 PyMuPDF。

## 使用

运行 `python scripts/install_skill.py`；更新已安装版本时使用 `--update`，旧文件会备份到技能目录之外。也可将 `skills/pdf-translate` 整个目录放入个人技能目录（通常是 `~/.codex/skills`）。在新会话调用 `$pdf-translate` 并提供英文 PDF 或图片；任务产物保存在工作区，不写入技能目录。

命令行入口用于助手的确定性处理，不会自行把英文机器翻译成中文；译文由助手按任务 JSON 提供。

```powershell
.\.venv\Scripts\python.exe skills\pdf-translate\scripts\pdf_translate.py prepare paper.pdf --job jobs\paper
```

图片/扫描件安装 `skills/pdf-translate/requirements-ocr.txt`（Python 3.10–3.12），然后使用 `prepare picture.png --job jobs/picture --ocr`。支持 PNG/JPEG/BMP/WebP/多页 TIFF，可输出 PDF 和 PNG。样式映射、图片区域核验和附件命令见 [详细说明](skills/pdf-translate/references/styles-media.md)。

## 验证与打包

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\package_skill.py
```

`examples/build_demo.py` 生成两页合成英文论文及已知译文，覆盖专名、双栏、表格、公式和位图补充说明。演示依赖 reportlab 与 Pillow（运行技能不需要这两项）；生成结果存于忽略的 `output/demo`。演示中的已知译文只用于验证，不是内置翻译引擎。

## 能力边界

复杂数学、字符轮廓化、特殊字体/背景及复杂表格仍需人工检查。OCR 字体需要人工标注，复杂背景不会自动覆盖；放不下的块保留原区域，输出草稿并在报告中给出完整译文。自动检查不能代替翻译质量和图表视觉审阅。

本项目不自动提交或推送文件。验证结果见 [v2 实现记录](docs/implementation-v2.md)，历史记录见 [v1](docs/implementation-v1.md)。

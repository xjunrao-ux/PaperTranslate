# PDF 翻译 Skill

英文 PDF → 中文译文 PDF + 英文在左、中文在右的内容块对齐 PDF。

v2 通过当前助手会话翻译，以本地 PyMuPDF 脚本提取和排版，无需单独的翻译 API。保留整段与段内粗斜体，支持本地图片 OCR 和 PDF 内嵌附件翻译。专名、人名按 `中文（English）` 展开；保存问题、裁决、术语和续跑状态。

当前源码引擎为 2.5.0：统一文章角色样式，完整保留公式与编号、表格行列、脚注分隔线及页码锚点。默认保留双栏，左侧直接复制原生内容，只为中文真实溢出增加必要留白；不将中文段距强加给英文。修正区域保留来源映射，矢量图和轮廓字可用缓存的双方向 OCR 识别标签。规则见 [页面契约](skills/pdf-translate/references/page-layout.md)，实现说明见 [v2.5 记录](docs/implementation-v2.5.md)。

技能入口：[skills/pdf-translate/SKILL.md](skills/pdf-translate/SKILL.md)。命令和 JSON 格式见 [工作流](skills/pdf-translate/references/workflow.md)。已确认需求见 [v1 规划](docs/v1-plan.md)。

发布版本：[v2.5.0 下载](https://github.com/xjunrao-ux/PaperTranslate/releases/tag/v2.5.0)，包含通用技能包、WorkBuddy 元数据包与 SHA-256 校验文件；详情见 [更新说明](docs/releases/v2.5.0.md)。

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
.\.venv\Scripts\python.exe skills\pdf-translate\scripts\pdf_translate.py start paper.pdf --job jobs\paper
```

流程分三段：准备并确认一次样式表；用 `next`／`apply` 批量翻译待译项；`build` 构建并检查，查看全部双语预览后 `finish` 统一核验导出。模型只接收紧凑待译包，不需逐块计算哈希和字符偏移。正文公式保留原生字形和分式结构，代码保留并提供中文说明。

`build <job>` 默认弹性段落对齐（paired），保留双栏／跨栏结构。严格原页用 `--alignment position`，自由单栏用 `--alignment paragraph`；正文按源段落结构选择 2em 或顶格，脚注与页码采用较小独立样式。实际核验后执行 `finish <job> --directory output/paper --reviewed-all --note "实际核验范围"`，生成 `paper__zh-CN__r01.pdf` 与 `paper__en-zh-CN__r01.pdf` 等交付文件。未核验只能用 `export --draft` 明确导出草稿。旧 prepare／import／render 协议保留兼容，不自动迁移旧任务。

图片/扫描件安装 `skills/pdf-translate/requirements-ocr.txt`（Python 3.10–3.12），然后使用 `start picture.png --job jobs/picture --ocr`，构建时使用 `--alignment position`。支持 PNG/JPEG/BMP/WebP/多页 TIFF，可输出 PDF 和 PNG。样式映射、图片区域核验和附件命令见 [详细说明](skills/pdf-translate/references/styles-media.md)。

## 验证与打包

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\package_skill.py
```

`examples/build_demo.py` 生成两页合成英文论文及已知译文，覆盖专名、双栏、表格、公式和位图补充说明。演示依赖 reportlab 与 Pillow（运行技能不需要这两项）；生成结果存于忽略的 `output/demo`。演示中的已知译文只用于验证，不是内置翻译引擎。

`examples/build_compact_demo.py` 演示新协议、统一中文样式、原生分式、密集单元格与图例保留。`package_skill.py --target workbuddy --output dist/pdf-translate-workbuddy-v2.5.0.zip` 补充 WorkBuddy 元数据；通用包供 Codex／DSH 等目录型技能宿主使用。各包共享核心脚本，尚未在 DSH 和 WorkBuddy 宿主内完成端到端实测；宿主仍须支持本地命令、UTF-8 文件和看图。

## 能力边界

复杂数学、字符轮廓化、特殊字体/背景及复杂表格仍需人工检查。OCR 字体需要人工标注，复杂背景不会自动覆盖；放不下的块保留原区域，输出草稿并在报告中给出完整译文。自动检查不能代替翻译质量和图表视觉审阅。

本项目不自动提交或推送文件。验证结果见 [v2 实现记录](docs/implementation-v2.md)，历史记录见 [v1](docs/implementation-v1.md)。

特殊标注（v2.4.1）：按译文片段保留文字颜色与下划线等样式，彩框、箭头与脚注记号绑定所属对象；复杂批注须实际核验，能力边界见 [记录](docs/implementation-v2.4.1.md)。

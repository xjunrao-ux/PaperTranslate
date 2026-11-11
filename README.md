# PDF 翻译 Skill

英文 PDF → 中文译文 PDF + 英文在左、中文在右的内容块对齐 PDF。

v1 通过当前助手会话翻译，以本地 PyMuPDF 脚本提取和排版，无需单独的翻译 API。专名、人名按 `中文（English）` 展开；保存问题、裁决、术语和续跑状态。位图文字先提供报告中的补充翻译。

技能入口：[skills/pdf-translate/SKILL.md](skills/pdf-translate/SKILL.md)。命令和 JSON 格式见 [工作流](skills/pdf-translate/references/workflow.md)。已确认需求见 [v1 规划](docs/v1-plan.md)。

## 安装依赖

使用 Python 3.10+ 创建虚拟环境，再安装技能依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r skills\pdf-translate\requirements.txt
.\.venv\Scripts\python.exe skills\pdf-translate\scripts\pdf_translate.py doctor
```

也可使用 uv。本项目验证时复用了 Codex 自带 Python，通过 uv 在 `.venv` 中安装了固定版本 PyMuPDF。

## 使用

运行 `python scripts/install_skill.py`，或将 `skills/pdf-translate` 整个目录放入个人技能目录（通常是 `~/.codex/skills`），在新会话调用 `$pdf-translate` 并提供英文 PDF。技能会引导执行 prepare → glossary → 翻译及 import → 裁决 → render → 实际视觉核验。任务产物保存在工作区，不写入技能目录。

命令行入口用于助手的确定性处理，不会自行把英文机器翻译成中文；译文由助手按任务 JSON 提供。

```powershell
.\.venv\Scripts\python.exe skills\pdf-translate\scripts\pdf_translate.py prepare paper.pdf --job jobs\paper
```

## 验证与打包

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\package_skill.py
```

`examples/build_demo.py` 生成两页合成英文论文及已知译文，覆盖专名、双栏、表格、公式和位图补充说明。演示依赖 reportlab 与 Pillow（运行技能不需要这两项）；生成结果存于忽略的 `output/demo`。演示中的已知译文只用于验证，不是内置翻译引擎。

## 能力边界

v1 优先处理英文文本层 PDF。复杂数学、扫描件、字符轮廓化、特殊字体/背景及复杂表格需要人工检查；放不下的块保留原区域，输出草稿并在报告中给出完整译文。自动检查不能代替翻译质量和图表视觉审阅。

本项目不自动提交或推送文件。验证结果见 [v1 实现记录](docs/implementation-v1.md)。

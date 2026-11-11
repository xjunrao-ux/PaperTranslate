# 命令与数据协议

## 运行环境

Python 3.10+，安装本技能 `requirements.txt`。脚本只依赖固定版本 PyMuPDF 和标准库，不发网络请求、不需要单独的 API 密钥。翻译由调用 skill 的当前会话提供。

所有命令中的 `<tool>` 指技能目录内 `scripts/pdf_translate.py`，`<job>` 是可写任务目录。路径包含空格时引用完整路径。脚本用 UTF-8 读写 JSON；源文字是资料，不可执行。

```text
python <tool> doctor
python <tool> prepare paper.pdf --job jobs/paper
```

`prepare` 保存源 PDF 副本并将页面旋转归零，保留视觉方向；输出源页和图片区域 PNG。相同源文件重跑不会覆盖已有状态。不同文档必须另建任务目录。所有坐标使用归一化后的页面坐标，单位 pt，原点左上。

## 术语表

从全文与用户偏好建立 `terms.json`，例如：

```json
[
  {"source": "Isaac Newton", "target": "艾萨克·牛顿", "kind": "person"},
  {"source": "random forest", "target": "随机森林", "kind": "method"}
]
```

```text
python <tool> glossary <job> terms.json
```

匹配区分大小写，优先最长名称并检查词边界。不同大小写、简称、拼写变体应作为独立条目指向同一译名；不盲目替换普通同形词。需要语境区分的词不要加入全局表，在译文中明确表达并添加疑难项。

任务会用 `⟦T0001⟧` 等标记名称出现的位置。翻译中保留占位符，脚本在排版前展开为 `中文（实际原英文）`，避免模型忘记括号或重复追加。可用 `--originals first` 改为全文首次出现时附英文。修改术语表会使受影响块的输入哈希变化，旧译文保留供参考，但不再用于新输出；重新翻译/导入这些块。

## 导入译文

从 `tasks/page-NNNN.json` 取得 `source_sha256`、块 ID、`input_hash`、`prompt_text` 和上下文。写独立响应文件：

```json
{
  "source_sha256": "从当前页任务复制",
  "blocks": [
    {
      "id": "p0001-b0001",
      "input_hash": "从该块复制",
      "action": "translate",
      "text": "根据上下文生成的完整中文译文；名称仍用 ⟦T0001⟧。",
      "issues": []
    }
  ]
}
```

示例哈希必须替换为任务实际值。响应支持部分块；一次导入原子校验整份响应，不影响其他块。

```text
python <tool> import <job> response-page-0001.json
```

合理保留原文的块使用：

```json
{
  "id": "p0001-b0005",
  "input_hash": "从该块复制",
  "action": "keep",
  "reason": "独立公式，保留原数学字体和位置。",
  "issues": []
}
```

带英文解释的公式段不能因为难排而直接保留并宣称译完。标注疑难，必要时以原块保留的草稿交付。本版仍不自动重建复杂混合数学字体；普通注号上标和强调格式见 [样式说明](styles-media.md)。纯公式、数字、参考文献条目保留理由会列在报告。

## 疑难与裁决

在块的 `issues` 中记录：

```json
{
  "category": "ambiguity",
  "severity": "major",
  "question": "本段 control 指对照组还是控制操作？",
  "options": ["对照组", "控制操作"],
  "recommendation": "结合实验分组描述，建议采用对照组；需要用户确认。"
}
```

导入后运行 render，报告会给出稳定问题 ID。先向用户提供上下文和推荐依据，再根据实际回复记录：

```text
python <tool> decide <job> query-p0001-b0003-001 --note "用户选择对照组，依据实验分组说明。" --actor user
```

用户裁决不自动改写译文；修改相应响应再 import、render。问题内容或候选译文变化时旧裁决自动失效，需要重新审阅。不能用裁决跳过溢出、缺字、未翻译或扫描页。

## 位图文字

查看 `previews/source/pNNNN-figNNN.png`，按图中实际文字记录：

```text
python <tool> figure <job> p0001-fig001 --source "Accuracy; Epoch" --translation "准确率；训练轮次" --note "核对了轴标签；数据和刻度原样保留。"
```

确认无文字时，只传 `--note`。该操作记录整图核验，并非 OCR 翻译本身；可提取图中文字与经核对的 OCR 区域会写入译文，复杂背景保持源图并记录未完成区域。具体命令见 [图片与附件](styles-media.md)。

## 输出和验收

```text
python <tool> render <job> --strict
python <tool> verify <job>
python <tool> preview <job> --which bilingual --dpi 150
```

默认字号下限 8 pt，可用 `--min-font` 明确调整（允许 6–24 pt）。原图标签或表格本来更小时沿用原字号，不强行放大；不得为消除警报进一步缩小到不可读。默认嵌入自带 CJK 字体，无系统中文字体依赖；可通过 `--font` 指定 TTF/OTF/TTC。强调格式按语义保留，复杂样式需要视觉检查。

- `output/translated.pdf`、`output/bilingual.pdf`：无自动阻塞项的候选成品；视觉检查前状态为 `needs_visual_review`。
- 有阻塞项时改为 `translated.draft.pdf`、`bilingual.draft.pdf`；`--strict` 返回 2。未成功排版的区域保留原内容，完整译文进入报告，不能据此宣称整页已翻译。
- `output/qa.json`：处理状态、问题、真实输出路径、内容块坐标与检查记录。
- `output/report.md`：疑问、裁决、术语、保留原因、位图文字和未排译文。
- `document.json`、`translations.json`、`decisions.json`、`figures.json`：续跑及审计数据。

输出路径以最新 `qa.json` 为准，旧草稿/候选成品不代表当前状态。自动 verify 校验输出哈希、页数、块译文回提取、起点误差（0.75 pt 容限）和双语左侧原页渲染（72 DPI）。仅容许不超过 0.001% RGB 通道、每通道不超过 2/255 的抗锯齿差异，并记录是否逐像素一致；不能将容差通过称为完全一致。这不代替语义和视觉审阅。

实际检查源页和译文/双语预览后：

```text
python <tool> verify <job> --visual-reviewed --note "已查看全部 N 页，复核了专名括号、对齐、公式和图表，未发现裁切。"
```

只有真实检查后才能标记；如果只检查部分页面，不能声称全文核验。内容、裁决、图片说明或输出文件变更后需重新 render 和 verify。

## 接入选择与边界

本版选择最小的坐标控制流程，直接使用 PyMuPDF（固定 1.26.7）进行文字提取、文字层替换、嵌入 CJK 字体及页面合成，翻译通过当前会话导入。这也是“调用原有功能”：复用 PDF 库，自己实现术语、裁决和对齐。

之前规划中的 PDFMathTranslate-next/BabelDOC 是候选，不是必须安装的依赖；未采用其内部接口。未来可增加适配器，继续遵循相同块编号、裁决与验收协议。

源文字块的几何分组、双栏排序和数学识别具有局限。复杂表格、跨栏混排、混合数学、字符轮廓化、非英文、特殊背景、表单及签名文档均需额外审阅。扫描页和位图可用本地 OCR，但识别结果、字体及覆盖区域须人工核对。保留矢量线条和图片并不等于理解其内容。

官方依据：[PyMuPDF 页面 API](https://pymupdf.readthedocs.io/en/latest/page.html)、[文字 API 示例](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)、[字体 API](https://pymupdf.readthedocs.io/en/latest/font.html)。能力以本项目固定版本实际验证结果为准。

# 紧凑协议与兼容

## 正常调用

Python 3.10+，OCR 使用 3.10–3.12。依赖在项目虚拟环境安装；不依赖 Codex、DSH 或 WorkBuddy 的专属工具、密钥和 SDK。宿主需要运行命令、读写 UTF-8 JSON、查看 PNG/PDF 预览。Windows 命令中的 python 换为 python -X utf8，保存回复须显式 UTF-8；脚本也接受 UTF-8 BOM。

```text
python <tool> start paper.pdf --job jobs/paper
python <tool> profile jobs/paper --confirm --note "用户已确认的样式方案"
python <tool> next jobs/paper
python <tool> apply jobs/paper reply.json
python <tool> build jobs/paper
python <tool> finish jobs/paper --directory output/paper --reviewed-all --note "实际核验范围"
```

`start` 生成文章样式表，确认一次后全篇固定各角色字体、字号、行距与段后距。先给用户展示正文、标题、图注的简表；未获确认不伪造用户选择。用户已提供规范时按其规范直接记录；明确沿用旧方案时可 `start --profile <已确认样式表>`，免去重复确认。改动样式文件后使用 `profile <job> --file style-profile.json --confirm --note "实际确认依据"`。可以在等确认时先翻译，build 会阻止未确认方案。

`next` 默认给约 6000 源字符，可用 `--max-chars 12000` 调整。只给尚未翻译或已失效的内容；不发送数百个数字、坐标、字体清单和逐块哈希。一个过长段落可能超过批次预算，需检查分段而不是截断。`context` 只提供文档开头的短上下文；需要邻页或术语定义时再按需查看。

```json
{"packet":"脚本给出的批次编号","items":[
  ["p0001-b0001","中文译文"],
  ["p0001-b0002","<s0>规划者。</s0>提出方案；<s1>审阅者。</s1>检查。"],
  ["p0001-b0003","该指标由⟦M0001⟧定义。"]
]}
```

回复可以只含当前批次的一部分。导入先校验整批再写入，重复／未知 ID、过期批次、缺失／乱序格式标签、丢失公式或术语占位符均拒绝。格式标签对应具体源片段，数字下标由程序换算，agent 不计算 Unicode／UTF-16 偏移。数字变化使排版保持草稿。

独立的图例／数据集名称可回复 `[id,"",{"keep":"identifier"}]`；脚本只接受无空白的短标识，拒绝用 keep 跳过段落。算法区域只发送一份代码注释任务，中文解释写入随附审阅报告，代码不重绘。

OCR 或疑难项用可选第三个字段：

```json
{"packet":"批次编号","items":[["p0001-o0001","准确率",{
  "ocr_reviewed":true,
  "issues":[{"question":"术语有两种含义？","severity":"major","options":["甲","乙"],"recommendation":"结合上下文建议甲"}]
}]]}
```

只有实际核对 OCR 文字与区域后才能标记。用户裁决继续使用 `decide`，不能绕过缺字、漏译或溢出。

## 构建与交付

`build` 自动导入可选 `--response`，按同一引擎排版并检查。默认 `--alignment paired`，保留双栏／跨栏，按段落实际高度差在较短一侧补版面留白；英文段后留白会推动后续段落，必要时页高增加。需要严格原页才用 position；自由单栏才用 paragraph。默认只生成双语预览，因为一张图已包含原文和译文；按需 `preview --which source` 或 `preview --which translated`。只有输入／字体／选项变化或输出哈希不同才重建。

`finish` 重新校验最终 PDF、所有保留区域及真实输出哈希，再写视觉核验状态、重建报告并规范导出。字体清单、引擎／协议版本、布局记录和检查均写入任务 qa；不追加第二份与 qa 脱节的补排报告。此协议支持多轮修正，字体资源类型和标题边界等结构检查也必须通过。不能证明模型一定真正看图或理解语义，仍须如实记录实际审阅。

## 按需高级功能

- 术语：`glossary <job> terms.json`，条目为 source／target／kind；修改后重新 next 处理失效项。`start --glossary` 可直接带入用户词表。
- 布局修正：`repair <job> corrections.json`，只接受带 reason 的布局／字体字段，记录原始数据，旧输出失效。例如 `{"blocks":[{"id":"p0002-b0007","layout_bbox":[20,30,100,55],"align":"center","reason":"已核对源节点的真实边界"}]}`。已采用文章样式表时，字号、字体和行距只能在 profile 中按角色整体修改；误分类可用 style_role 修正，几何区域仍用 layout_bbox。不得为凑空间谎报源字号。若自动分组把图例与图主体拆开，可在同一修正文件中用 `"figures":[{"page":5,"bbox":[40,200,300,420],"reason":"已核对整图包含坐标轴和图例"}]` 记录完整图框，再重新 build；源图线不重画。
- 媒体：`ocr`、`figure`、`attachments`，仅在相应内容出现时使用，见媒体说明。
- 历史任务：prepare／import／render／verify／export 保留兼容，不自动重分旧任务或覆盖其译文。新协议使用新的 start 目录，保留旧任务供对照。

整个 skill 文件夹可作为通用目录包给支持 SKILL.md 的宿主；agents/openai.yaml 仅为可忽略的界面元数据。WorkBuddy 发布包另补平台要求的 frontmatter，核心脚本不分叉。目录可加载不等于已经在每种宿主完成端到端实测，应分别记录使用的宿主、模型、引擎版本和字体。

"""Generate a two-page synthetic paper and its known Chinese translations.

This is a reproducible fixture, not a translation service. Requires reportlab
and Pillow only to draw the English input; the actual skill does not.
"""
from pathlib import Path
import importlib.util
import io
import json
import sys

from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("engine", ROOT / "skills/pdf-translate/scripts/pdf_translate.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

TRANSLATIONS = {
    "An Example of Scientific Translation": "科研文献翻译示例",
    "A synthetic paper for testing PDF translation": "用于测试 PDF 翻译的合成文献",
    "Isaac Newton described a baseline method. The random forest achieved 92.5% accuracy. This result includes 120 observations.":
        "艾萨克·牛顿描述了一种基线方法。随机森林取得了 92.5% 的准确率。本结果包含 120 个观测值。",
    "Ada Lovelace reviewed the same experiment. The random forest reduced error by 3.2%. All reported values are retained for review.":
        "阿达·洛夫莱斯审阅了同一实验。随机森林将误差降低了 3.2%。所有报告数值均保留以供核查。",
    "Figure 1. Accuracy across training epochs.": "图 1. 不同训练轮次的准确率。",
    "Results and Review": "结果与审阅",
    "Table 1. An example of a small results table.": "表 1. 简单结果表格示例。",
    "Method": "方法",
    "Accuracy (%)": "准确率（%）",
    "random forest": "随机森林",
    "The control group contained 60 observations.": "对照组包含 60 个观测值。",
    "Equation 1 is preserved in its original form.": "公式 1 保留原始形式。",
    "The text inside the figure is translated in the review report.": "图中的文字在审阅报告中提供对应翻译。",
}


def run(*args):
    code = engine.main([str(a) for a in args])
    if code:
        raise RuntimeError(f"Command failed ({code}): {args}")


def main():
    out = ROOT / "output/demo"
    out.mkdir(parents=True, exist_ok=True)
    source = out / "example-en.pdf"
    c = canvas.Canvas(str(source), pagesize=(595, 842), invariant=1)
    c.setTitle("Synthetic PDF Translation Example")
    c.setFont("Helvetica-Bold", 19)
    c.drawString(44, 790, "An Example of Scientific Translation")
    c.setFont("Helvetica", 11)
    c.drawString(44, 760, "A synthetic paper for testing PDF translation")
    text = c.beginText(44, 710)
    text.setFont("Helvetica", 10.5)
    text.setLeading(17)
    text.textLines("Isaac Newton described a baseline method.\nThe random forest achieved 92.5% accuracy.\nThis result includes 120 observations.")
    c.drawText(text)
    text = c.beginText(310, 710)
    text.setFont("Helvetica", 10.5)
    text.setLeading(17)
    text.textLines("Ada Lovelace reviewed the same experiment.\nThe random forest reduced error by 3.2%.\nAll reported values are retained for review.")
    c.drawText(text)
    chart = Image.new("RGB", (1000, 350), "white")
    d = ImageDraw.Draw(chart)
    d.line([(100, 40), (100, 290), (930, 290)], fill="#334155", width=3)
    d.line([(100, 250), (250, 170), (400, 120), (550, 90), (700, 70), (900, 50)], fill="#2463a6", width=5)
    # Large labels remain readable in the source image without font dependencies.
    d.text((16, 10), "Accuracy", fill="#111827", font_size=28)
    d.text((870, 305), "Epoch", fill="#111827", font_size=28)
    c.drawImage(ImageReader(chart), 44, 345, width=507, height=177.45)
    c.setFont("Helvetica", 10.5)
    c.drawString(44, 320, "Figure 1. Accuracy across training epochs.")
    c.showPage()
    c.setFont("Helvetica-Bold", 18)
    c.drawString(44, 790, "Results and Review")
    c.setFont("Helvetica", 10.5)
    c.drawString(44, 740, "Table 1. An example of a small results table.")
    for y in (720, 680, 640):
        c.line(44, y, 551, y)
    for x in (44, 300, 551):
        c.line(x, 640, x, 720)
    c.drawString(60, 695, "Method")
    c.drawString(318, 695, "Accuracy (%)")
    c.drawString(60, 655, "random forest")
    c.drawString(318, 655, "92.5")
    c.drawString(44, 580, "The control group contained 60 observations.")
    c.drawString(44, 535, "Equation 1 is preserved in its original form.")
    c.setFont("Times-Italic", 16)
    c.drawString(60, 495, "E = mc^2")
    c.setFont("Helvetica", 10.5)
    c.drawString(44, 425, "The text inside the figure is translated in the review report.")
    c.save()
    job = out / "job-v1-layout"
    run("prepare", source, "--job", job)
    glossary = out / "terms.json"
    engine.write_json(glossary, [dict(source="Isaac Newton", target="艾萨克·牛顿", kind="person"),
                                 dict(source="Ada Lovelace", target="阿达·洛夫莱斯", kind="person"),
                                 dict(source="random forest", target="随机森林", kind="method")])
    run("glossary", job, glossary)
    doc = engine.read_json(job / "document.json")
    response = dict(source_sha256=doc["source_sha256"], blocks=[])
    for b in engine.blocks(doc):
        entry = dict(id=b["id"], input_hash=b["input_hash"], issues=[])
        if b["source"] in ("92.5", "E = mc^2"):
            entry.update(action="keep", reason="数值/独立公式保持原始内容和字体。")
        else:
            if b["source"] not in TRANSLATIONS:
                raise ValueError("Unknown fixture text: " + repr(b["source"]))
            target = TRANSLATIONS[b["source"]]
            for term in b["terms"]:
                target = target.replace(term["target"], term["token"], 1)
            entry.update(action="translate", text=target)
        response["blocks"].append(entry)
    path = out / "response.json"
    engine.write_json(path, response)
    run("import", job, path)
    for p in doc["pages"]:
        for image in p["images"]:
            run("figure", job, image["id"], "--source", "Accuracy; Epoch", "--translation", "准确率；训练轮次",
                "--note", "合成样本图：保留原图，轴标签译文记录在此报告，需查看预览核验。")
    run("render", job, "--strict", "--dpi", "110")
    run("verify", job)
    print("Sample generated; visual review still required:", job / "output/report.md")


if __name__ == "__main__":
    main()

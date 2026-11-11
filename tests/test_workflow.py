"""Observable PDF invariants; run with python -m unittest discover -s tests -v."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pdf_translate", ROOT / "skills/pdf-translate/scripts/pdf_translate.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class Workflow(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.pdf"
        self.job = self.root / "job"

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *args, code=0):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
            actual = engine.main([str(a) for a in args])
        self.assertEqual(code, actual, errors.getvalue())

    def make_pdf(self, text="Isaac Newton used a random forest in 2024.", image=False, rotate=0, low=False):
        doc = fitz.open()
        p = doc.new_page(width=500, height=500)
        p.insert_textbox(fitz.Rect(45, 450 if low else 50, 455, 495 if low else 100), text,
                         fontsize=11, fontname="helv")
        if image:
            picture = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 30, 30), False)
            picture.clear_with(230)
            p.insert_image(fitz.Rect(70, 160, 200, 260), pixmap=picture)
        p.draw_line((45, 140), (455, 140), color=(0.2, 0.3, 0.4))
        if rotate:
            p.set_rotation(rotate)
        doc.save(self.source)
        doc.close()
        self.call("prepare", self.source, "--job", self.job)

    def terms(self, originals="every"):
        path = self.root / "terms.json"
        engine.write_json(path, [dict(source="Isaac Newton", target="艾萨克·牛顿", kind="person"),
                                 dict(source="random forest", target="随机森林", kind="method")])
        self.call("glossary", self.job, path, "--originals", originals)

    def model(self):
        return engine.read_json(self.job / "document.json")

    def response(self, text="⟦T0001⟧在 2024 年使用了⟦T0002⟧。", **extra):
        doc = self.model()
        b = engine.blocks(doc)[0]
        data = dict(source_sha256=doc["source_sha256"], blocks=[dict(
            id=b["id"], input_hash=b["input_hash"], text=text, **extra)])
        path = self.root / "response.json"
        engine.write_json(path, data)
        return path

    def qa(self):
        return engine.read_json(self.job / "output/qa.json")

    def render(self, code=0):
        self.call("render", self.job, "--strict", "--dpi", "36", code=code)

    def test_translated_pdf_has_parentheses_and_original_left_is_identical(self):
        self.make_pdf()
        source_hash = engine.file_hash(self.source)
        self.terms()
        self.call("import", self.job, self.response())
        self.render()
        self.call("verify", self.job)
        qa = self.qa()
        self.assertEqual("needs_visual_review", qa["status"])
        with fitz.open(qa["translated"]) as doc:
            text = doc[0].get_text()
            self.assertIn("艾萨克·牛顿（Isaac Newton）", text)
            self.assertIn("随机森林（random forest）", text)
            self.assertEqual(1, len(doc[0].get_drawings()))
        self.assertEqual(source_hash, engine.file_hash(self.source))
        self.assertLessEqual(max(q["actual_anchor_error_pt"] for q in qa["checks"]), 0.75)

    def test_missing_token_and_duplicate_token_are_rejected_atomically(self):
        self.make_pdf()
        self.terms()
        before = engine.read_json(self.job / "translations.json")
        for text in ("在 2024 年用了随机森林。", "⟦T0001⟧⟦T0001⟧⟦T0002⟧ 2024"):
            self.call("import", self.job, self.response(text), code=1)
        self.assertEqual(before, engine.read_json(self.job / "translations.json"))

    def test_numbers_change_creates_draft_and_prevents_verification(self):
        self.make_pdf()
        self.terms()
        self.call("import", self.job, self.response("⟦T0001⟧在 2025 年使用了⟦T0002⟧。"))
        self.render(code=2)
        self.assertTrue(any(q["id"].startswith("numbers-") for q in self.qa()["blockers"]))
        self.call("verify", self.job, code=1)

    def test_overflow_preserves_original_and_full_translation_in_report(self):
        self.make_pdf("A result in 2024.", low=True)
        text = "2024 年，" + "这是必须完整保留的译文。" * 200
        self.call("import", self.job, self.response(text))
        self.render(code=2)
        self.assertTrue(any(q["id"].startswith("overflow-") for q in self.qa()["blockers"]))
        with fitz.open(self.qa()["translated"]) as pdf:
            self.assertIn("A result", pdf[0].get_text())
        self.assertIn(text, (self.job / "output/report.md").read_text(encoding="utf-8"))

    def test_major_question_requires_decision_and_changed_question_invalidates_it(self):
        self.make_pdf("A control in 2024.")
        question = dict(question="control 的含义？", severity="major", options=["对照组", "控制"])
        self.call("import", self.job, self.response("2024 年的对照组。", issues=[question]))
        self.render(code=2)
        query = next(q for q in self.qa()["issues"] if q["id"].startswith("query-"))
        self.call("decide", self.job, query["id"], "--note", "用户选择对照组。")
        self.render()
        self.call("verify", self.job)
        question["question"] = "control 在另一个上下文中的含义？"
        self.call("import", self.job, self.response("2024 年的对照组。", issues=[question]))
        self.render(code=2)

    def test_glossary_update_invalidates_old_translation(self):
        self.make_pdf()
        self.terms()
        self.call("import", self.job, self.response())
        self.render()
        terms = self.root / "terms2.json"
        engine.write_json(terms, [dict(source="Isaac Newton", target="牛顿", kind="person")])
        self.call("glossary", self.job, terms)
        self.call("verify", self.job, code=1)
        self.render(code=2)
        self.assertTrue(any(q["id"].startswith("stale-") for q in self.qa()["blockers"]))

    def test_unreviewed_image_blocks_final_and_figure_note_invalidates_output(self):
        self.make_pdf(image=True)
        self.terms()
        self.call("import", self.job, self.response())
        self.render(code=2)
        image_id = self.model()["pages"][0]["images"][0]["id"]
        self.call("figure", self.job, image_id, "--note", "测试夹具为纯色无文字位图。")
        self.call("verify", self.job, code=1)
        self.render()
        self.call("verify", self.job)
        self.call("figure", self.job, image_id, "--note", "更新核对说明。")
        self.call("verify", self.job, code=1)

    def test_prepare_resume_does_not_overwrite_translations(self):
        self.make_pdf()
        self.terms()
        self.call("import", self.job, self.response())
        before = engine.file_hash(self.job / "translations.json")
        self.call("prepare", self.source, "--job", self.job)
        self.assertEqual(before, engine.file_hash(self.job / "translations.json"))

    def test_missing_blocks_are_not_treated_as_translated(self):
        self.make_pdf()
        self.render(code=2)
        self.assertEqual(0, self.qa()["translated_blocks"])
        self.assertTrue(self.qa()["blockers"])

    def test_formula_can_be_kept_without_altering_its_appearance(self):
        self.make_pdf("E = mc^2")
        self.call("import", self.job, self.response("", action="keep", reason="独立公式保留原样。"))
        self.render()
        self.call("verify", self.job)
        with fitz.open(self.job / "source.pdf") as source, fitz.open(self.qa()["translated"]) as out:
            self.assertEqual(source[0].get_pixmap().samples, out[0].get_pixmap().samples)

    def test_scanned_page_is_flagged(self):
        doc = fitz.open()
        doc.new_page()
        doc.save(self.source)
        doc.close()
        self.call("prepare", self.source, "--job", self.job)
        self.render(code=2)
        self.assertTrue(any(q["id"].startswith("scan-") for q in self.qa()["blockers"]))

    def test_first_occurrence_mode(self):
        self.make_pdf("Isaac Newton and Isaac Newton.")
        self.terms("first")
        b = engine.blocks(self.model())[0]
        self.assertEqual([True, False], [t["original"] for t in b["terms"]])
        self.assertEqual("牛顿（Isaac Newton）与牛顿。", engine.expanded(
            dict(terms=[dict(t, target="牛顿") for t in b["terms"]]), dict(text="⟦T0001⟧与⟦T0002⟧。")))

    def test_chinese_closing_punctuation_does_not_start_a_line(self):
        font = fitz.Font("china-s")
        lines = engine.wrap_text("这是需要正常换行的中文句子。", 52, font, 10)
        self.assertFalse(any(line.startswith("。") for line in lines))
        self.assertEqual("这是需要正常换行的中文句子。", "".join(lines))

    def test_table_translation_uses_cell_width_and_preserves_rules(self):
        pdf = fitz.open()
        page = pdf.new_page(width=500, height=500)
        for y in (40, 80, 120):
            page.draw_line((40, y), (460, y))
        for x in (40, 250, 460):
            page.draw_line((x, 40), (x, 120))
        page.insert_text((55, 62), "Method", fontsize=11)
        page.insert_text((55, 102), "random forest", fontsize=11)
        page.insert_text((270, 62), "Accuracy", fontsize=11)
        page.insert_text((270, 102), "92.5", fontsize=11)
        pdf.save(self.source)
        pdf.close()
        self.call("prepare", self.source, "--job", self.job)
        self.terms()
        doc = self.model()
        response = dict(source_sha256=doc["source_sha256"], blocks=[])
        mapping = {"Method": "方法", "random forest": "⟦T0001⟧", "Accuracy": "准确率"}
        for b in engine.blocks(doc):
            entry = dict(id=b["id"], input_hash=b["input_hash"])
            self.assertIsNotNone(b["cell_bbox"])
            if b["source"] == "92.5":
                entry.update(action="keep", reason="保留数值。")
            else:
                entry["text"] = mapping[b["source"]]
            response["blocks"].append(entry)
        path = self.root / "table.json"
        engine.write_json(path, response)
        self.call("import", self.job, path)
        self.render()
        self.call("verify", self.job)
        plan = next(p for p in self.qa()["layouts"] if "random forest" in p["target"])
        self.assertEqual(1, len(plan["lines"]))
        with fitz.open(self.qa()["translated"]) as out:
            self.assertEqual(6, len(out[0].get_drawings()))


if __name__ == "__main__":
    unittest.main()

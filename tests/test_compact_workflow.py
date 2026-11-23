"""Portable packets, native equations, preserved legends and one delivery state."""
import contextlib
import io
import json
from pathlib import Path
import unittest
import pymupdf as fitz
import test_workflow as baseline

e=baseline.engine


class Compact(unittest.TestCase):
    setUp=baseline.Workflow.setUp
    tearDown=baseline.Workflow.tearDown
    call=baseline.Workflow.call
    model=baseline.Workflow.model
    qa=baseline.Workflow.qa

    def start(self):
        self.call('start',self.source,'--job',self.job)
        self.call('profile',self.job,'--confirm','--actor','assistant','--note','隔离测试夹具采用固定样式，不代表用户确认。')

    def packet(self):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):self.assertEqual(0,e.main(['next',str(self.job)]))
        return json.loads(stream.getvalue())

    def apply(self,packet,mapping):
        path=self.root/'answers.json'
        e.write_json(path,dict(packet=packet['packet'],items=[[i[0],mapping(i[1])] for i in packet['items']]))
        self.call('apply',self.job,path)
        return path

    def simple(self):
        doc=fitz.open();p=doc.new_page(width=350,height=350)
        p.insert_text((40,50),'Method',fontsize=11)
        p.insert_text((40,90),'2024',fontsize=11)
        doc.save(self.source);doc.close();self.start()

    def test_compact_packet_auto_keeps_numbers_and_has_no_repeated_hashes_or_coordinates(self):
        self.simple();packet=self.packet()
        self.assertEqual(1,len(packet['items']))
        self.assertFalse((self.job/'context.md').exists())
        raw=json.dumps(packet)
        self.assertNotIn('input_hash',raw);self.assertNotIn('bbox',raw)
        self.apply(packet,lambda text:'方法')
        self.assertEqual(0,self.packet()['pending'])

    def test_occurrence_tags_reject_reordered_reviewer_and_resolve_unicode_offsets(self):
        doc=fitz.open();p=doc.new_page(width=550,height=300);w=fitz.TextWriter(p.rect)
        w.append((40,70),'Reviewer appears. ',font=fitz.Font('helv'),fontsize=11)
        w.append(w.last_point,'Planner.',font=fitz.Font('hebo'),fontsize=11)
        w.append(w.last_point,' proposes; ',font=fitz.Font('helv'),fontsize=11)
        w.append(w.last_point,'Reviewer.',font=fitz.Font('hebo'),fontsize=11)
        w.append(w.last_point,' checks.',font=fitz.Font('helv'),fontsize=11)
        w.write_text(p);doc.save(self.source);doc.close();self.start()
        packet=self.packet();bid=packet['items'][0][0]
        wrong=dict(packet=packet['packet'],items=[[bid,'<s1>审阅者。</s1><s0>规划者。</s0>']])
        file=self.root/'bad.json';e.write_json(file,wrong);self.call('apply',self.job,file,code=1)
        self.apply(packet,lambda text:'先提到审阅者。<s0>规划者。</s0>提出方案；<s1>审阅者。</s1>检查。')
        tr=e.read_json(self.job/'translations.json')[bid]
        self.assertEqual(['规划者。','审阅者。'],[tr['text'][s['start']:s['end']] for s in tr['styles']])

    def test_semantic_paragraphs_and_caption_equals_do_not_become_math_blocks(self):
        doc=fitz.open();p=doc.new_page(width=500,height=350)
        p.insert_text((40,60),'Table caption (1000 = baseline).',fontsize=11)
        w=fitz.TextWriter(p.rect)
        w.append((40,100),'Planner.',font=fitz.Font('hebo'),fontsize=11)
        w.append(w.last_point,' Proposes changes.',font=fitz.Font('helv'),fontsize=11)
        w.append((40,115),'Reviewer.',font=fitz.Font('hebo'),fontsize=11)
        w.append(w.last_point,' Reviews changes.',font=fitz.Font('helv'),fontsize=11)
        w.write_text(p);doc.save(self.source);doc.close();self.start()
        blocks=e.blocks(self.model())
        self.assertEqual(3,len(blocks));self.assertTrue(all(b['kind']=='text' for b in blocks))

    def test_inline_native_formula_keeps_symbol_font_and_subscript(self):
        doc=fitz.open();p=doc.new_page(width=400,height=350);w=fitz.TextWriter(p.rect)
        w.append((40,70),'The value ',font=fitz.Font('tiro'),fontsize=12)
        x=w.last_point.x
        w.append((x,70),'α',font=fitz.Font('symb'),fontsize=12)
        w.append((x+8,73),'b',font=fitz.Font('tiro'),fontsize=7)
        w.append((x+13,70),' is stable.',font=fitz.Font('tiro'),fontsize=12)
        w.write_text(p);doc.save(self.source);doc.close();self.start()
        packet=self.packet();self.assertIn('⟦M0001⟧',packet['items'][0][1])
        self.apply(packet,lambda text:'数值⟦M0001⟧保持稳定。')
        self.call('build',self.job,'--alignment','paragraph','--dpi',36)
        plan=self.qa()['layouts'][0];self.assertTrue(any(s.get('native_math') for s in plan['segments']))
        with fitz.open(self.qa()['translated']) as out:
            spans=[s for b in out[0].get_text('dict')['blocks'] if b['type']==0 for l in b['lines'] for s in l['spans']]
            self.assertTrue(any('Symbol' in s['font'] for s in spans))
            self.assertTrue(any(s['text']=='b' and s['size']<9 for s in spans))

    def test_build_has_no_intermediate_pdf_is_cached_and_finish_revalidates_bytes(self):
        self.simple();self.apply(self.packet(),lambda text:'方法')
        self.call('build',self.job,'--alignment','paragraph','--dpi',36)
        qa=self.qa();path=Path(qa['translated']);before=path.stat().st_mtime_ns
        self.assertFalse((self.job/'output/bilingual.draft.pdf').exists())
        self.assertFalse((self.job/'output/translated.pdf').exists())
        self.assertFalse((self.job/'previews/translated').exists())
        self.call('build',self.job,'--alignment','paragraph','--dpi',36);self.assertEqual(before,path.stat().st_mtime_ns)
        self.call('finish',self.job,'--directory',self.root/'exports','--note','未看图。',code=1)
        self.call('finish',self.job,'--directory',self.root/'exports','--reviewed-all','--note','隔离夹具模拟视觉核验，不用于实际文献。')
        self.assertTrue((self.root/'exports/source__zh-CN__r01.pdf').is_file())
        path.write_bytes(path.read_bytes()+b'\nchanged')
        self.call('finish',self.job,'--directory',self.root/'exports','--revision',2,'--reviewed-all','--note','模拟。',code=1)

    def test_preserved_legend_is_checked_in_its_region(self):
        doc=fitz.open();p=doc.new_page(width=300,height=300)
        p.insert_text((40,50),'Caption',fontsize=11)
        p.insert_text((40,120),'VPR-Evolve',fontsize=8)
        doc.save(self.source);doc.close();self.start()
        model=self.model();tr=e.read_json(self.job/'translations.json')
        for b in e.blocks(model):
            if b['source']=='VPR-Evolve':tr[b['id']]=dict(input_hash=b['input_hash'],action='keep',reason='方法标识',keep_kind='identifier')
        e.write_json(self.job/'translations.json',tr)
        self.apply(self.packet(),lambda text:'图注')
        self.call('build',self.job,'--alignment','position','--dpi',36)
        self.assertTrue(self.qa()['preserved_checks'])
        q=self.qa()
        with fitz.open(q['translated']) as pdf:
            r=pdf[0].search_for('VPR-Evolve')[0];pdf[0].add_redact_annot(r);pdf[0].apply_redactions()
            altered=pdf.tobytes()
        Path(q['translated']).write_bytes(altered)
        # Simulate a postprocessor updating a hash but failing to retain a legend.
        q['output_hashes'][q['translated']]=e.file_hash(q['translated']);e.write_json(self.job/'output/qa.json',q)
        self.call('verify',self.job,code=1)

    def test_native_fraction_bar_stays_with_numerator_and_denominator(self):
        doc=fitz.open();p=doc.new_page(width=400,height=350);w=fitz.TextWriter(p.rect)
        w.append((40,70),'The ratio ',font=fitz.Font('tiro'),fontsize=12)
        x=w.last_point.x+2
        w.append((x,64),'α',font=fitz.Font('symb'),fontsize=7)
        w.append((x,75),'β',font=fitz.Font('symb'),fontsize=7)
        w.append((x+13,70),' is positive.',font=fitz.Font('tiro'),fontsize=12)
        w.write_text(p);p.draw_line((x-1,68),(x+9,68),width=.5)
        doc.save(self.source);doc.close();self.start()
        packet=self.packet();maths=[o for b in e.blocks(self.model()) for o in b.get('protected_math',[])]
        self.assertEqual(1,len(maths))
        self.apply(packet,lambda text:'该比值⟦M0001⟧为正。')
        self.call('build',self.job,'--alignment','paragraph','--dpi',36)
        with fitz.open(self.qa()['translated']) as out:
            spans=[s for b in out[0].get_text('dict')['blocks'] if b['type']==0 for l in b['lines'] for s in l['spans']]
            self.assertTrue(any('α' in s['text'] for s in spans));self.assertTrue(any('β' in s['text'] for s in spans))
            self.assertTrue(any(d['width']==.5 for d in out[0].get_drawings()))

    def test_repair_is_tracked_and_report_cannot_inherit_appended_completion_claim(self):
        self.simple();self.apply(self.packet(),lambda text:'方法')
        bid=next(b['id'] for b in e.blocks(self.model()) if b['source']=='Method')
        f=self.root/'repair.json';e.write_json(f,dict(blocks=[dict(id=bid,layout_bbox=[40,40,140,80],align='left',reason='核对了可用留白。')]))
        self.call('repair',self.job,f)
        self.call('build',self.job,'--alignment','paragraph','--dpi',36)
        self.assertIn('extracted_bbox',next(b for b in e.blocks(self.model()) if b['id']==bid))
        self.call('finish',self.job,'--directory',self.root/'one','--reviewed-all','--note','测试夹具模拟视觉检查。')
        report=self.job/'output/report.md';report.write_text(report.read_text(encoding='utf-8')+'UNTRACKED CLAIM',encoding='utf-8')
        self.call('export',self.job,'--directory',self.root/'two')
        self.assertNotIn('UNTRACKED CLAIM',(self.root/'two/source__review__r01.md').read_text(encoding='utf-8'))

    def test_code_is_preserved_and_gets_one_annotation_task(self):
        doc=fitz.open();p=doc.new_page(width=500,height=350)
        p.draw_line((40,40),(460,40));p.draw_line((40,160),(460,160))
        p.insert_text((40,52),'Algorithm 1 Example',fontsize=10,fontname='hebo')
        p.insert_text((40,72),['Require: input','for each candidate','    evaluate(candidate)','return best'],fontsize=9,fontname='cour')
        doc.save(self.source);doc.close();self.start()
        packet=self.packet();notes=[i for i in packet['items'] if len(i)>2 and i[2].get('role')=='code_annotation']
        self.assertEqual(1,len(notes))
        file=self.root/'notes.json';e.write_json(file,dict(packet=packet['packet'],items=[
            [i[0],'中文解释：接收输入，逐一评估候选并返回最佳结果。' if i in notes else '算法 1 示例'] for i in packet['items']]))
        self.call('apply',self.job,file);self.call('build',self.job,'--alignment','paragraph','--dpi',36)
        self.assertIn('中文解释',(self.job/'output/report.md').read_text(encoding='utf-8'))

    def test_packet_is_rejected_after_terminology_changes(self):
        self.simple();packet=self.packet()
        file=self.root/'terms.json';e.write_json(file,[dict(source='Method',target='方法')])
        self.call('glossary',self.job,file)
        response=self.root/'old.json';e.write_json(response,dict(packet=packet['packet'],items=[[packet['items'][0][0],'方法']]))
        self.call('apply',self.job,response,code=1)

    def test_article_styles_are_confirmed_once_then_unify_body_font_size_and_spacing(self):
        doc=fitz.open();p=doc.new_page(width=420,height=500)
        p.insert_text((40,70),'First body paragraph.',fontsize=11,fontname='tiro')
        p.insert_text((40,125),'Second body paragraph.',fontsize=11.2,fontname='helv')
        doc.save(self.source);doc.close()
        self.call('start',self.source,'--job',self.job)
        packet=self.packet()
        self.apply(packet,lambda text:'这是按照同一篇文章的统一样式排版的中文段落，行距与段后留白稍微放松，保持阅读舒适。')
        self.call('build',self.job,'--alignment','paragraph','--dpi',36,code=1)
        self.call('profile',self.job,'--confirm','--actor','assistant','--note','测试夹具模拟确认全文样式。')
        self.call('build',self.job,'--alignment','paragraph','--dpi',36)
        body=self.model()['style_profile']['roles']['body'];plans=self.qa()['layouts']
        self.assertEqual({body['font_size']},{p['size'] for p in plans})
        self.assertEqual(1,len({p['font_policy']['font'] for p in plans}))
        self.assertTrue(all(abs(p['line_height']-body['line_height'])<.01 for p in plans))
        pairs=self.qa()['paragraph_pairs']
        self.assertAlmostEqual(body['paragraph_gap'],pairs[1]['top']-pairs[0]['top']-pairs[0]['height'],places=3)


if __name__=='__main__':unittest.main()

"""Source-matched typography, dense cells, and portable deliverable exports."""
from argparse import Namespace
from pathlib import Path
import unittest
from unittest.mock import patch
import pymupdf as fitz
import test_workflow as baseline

engine=baseline.engine


class TypographyExport(unittest.TestCase):
    setUp=baseline.Workflow.setUp
    tearDown=baseline.Workflow.tearDown
    call=baseline.Workflow.call
    make_pdf=baseline.Workflow.make_pdf
    model=baseline.Workflow.model
    response=baseline.Workflow.response
    qa=baseline.Workflow.qa
    render=baseline.Workflow.render

    def import_all(self, mapping):
        doc=self.model()
        entries=[dict(id=b['id'],input_hash=b['input_hash'],text=mapping[b['source']]) for b in engine.blocks(doc)]
        path=self.root/'all.json'
        engine.write_json(path,dict(source_sha256=doc['source_sha256'],blocks=entries))
        self.call('import',self.job,path)

    def test_serif_and_sans_match_source_and_embed_fonts(self):
        pdf=fitz.open();p=pdf.new_page(width=500,height=500)
        p.insert_text((45,65),'Serif body',fontname='tiro',fontsize=11)
        p.insert_text((45,165),'Sans caption',fontname='helv',fontsize=9)
        pdf.save(self.source);pdf.close()
        self.call('prepare',self.source,'--job',self.job)
        self.import_all({'Serif body':'衬线正文','Sans caption':'无衬线图注'})
        self.render();self.call('verify',self.job)
        plans=self.qa()['layouts']
        for plan in plans:
            self.assertTrue(plan['font_policy']['family_match'])
            self.assertEqual(plan['source_typography']['font_size'],plan['size'])
        self.assertNotEqual(plans[0]['font_policy']['font'],plans[1]['font_policy']['font'])
        with fitz.open(self.qa()['translated']) as pdf:
            names={s['font'] for b in pdf[0].get_text('dict')['blocks'] if b['type']==0 for l in b['lines'] for s in l['spans']}
            for plan in plans: self.assertIn(plan['font_policy']['font'].replace(' Regular','').replace(' ',''),{n.replace(' ','') for n in names})
            embedded=[pdf.extract_font(x[0])[3] for x in pdf[0].get_fonts() if x[1] not in ('n/a','')]
            self.assertGreaterEqual(len(embedded),2)
            self.assertTrue(all(embedded))

    def test_body_baseline_spacing_and_large_title_preserved(self):
        pdf=fitz.open();p=pdf.new_page(width=500,height=500)
        p.insert_text((45,65),'Large title',fontname='tiro',fontsize=30)
        p.insert_text((45,140),['First source line','Second source line'],fontname='tiro',fontsize=10,lineheight=1.45)
        pdf.save(self.source);pdf.close()
        self.call('prepare',self.source,'--job',self.job)
        self.import_all({'Large title':'大标题','First source line Second source line':'第一行中文\n第二行中文'})
        self.render();self.call('verify',self.job)
        title,body=self.qa()['layouts']
        self.assertEqual(30,title['size'])
        self.assertAlmostEqual(14.5,body['line_height'],places=2)
        with fitz.open(self.qa()['translated']) as out:
            spans=[s for b in out[0].get_text('dict')['blocks'] if b['type']==0 for l in b['lines'] for s in l['spans']]
            body_spans=[s for s in spans if abs(s['size']-10)<.01]
            self.assertEqual(2,len(body_spans))
            self.assertAlmostEqual(14.5,body_spans[1]['origin'][1]-body_spans[0]['origin'][1],places=2)

    def test_dense_cells_and_label_use_original_5pt_size_without_crossing_rules(self):
        pdf=fitz.open();p=pdf.new_page(width=300,height=200)
        for y in (40,45.6,53.6):p.draw_line((40,y),(260,y),width=.2)
        for x in (40,150,260):p.draw_line((x,40),(x,53.6),width=.2)
        p.insert_text((42,44.9),'Method',fontname='tiro',fontsize=5.1)
        p.insert_text((152,44.9),'Score',fontname='tiro',fontsize=5.1)
        p.insert_text((42,51.9),'Planner',fontname='tiro',fontsize=6)
        p.insert_text((152,51.9),'Coder',fontname='tiro',fontsize=6)
        p.draw_rect((40,80,130,85.7),width=.2)
        p.insert_text((42,84.9),'Stage Packing',fontname='helv',fontsize=5.1)
        pdf.save(self.source);pdf.close()
        self.call('prepare',self.source,'--job',self.job)
        mapping={'Method':'方法','Score':'得分','Planner':'规划器','Coder':'编码器','Stage Packing':'阶段打包'}
        self.import_all(mapping)
        self.render();self.call('verify',self.job)
        self.assertEqual(5,self.qa()['translated_blocks'])
        index={b['id']:b for b in engine.blocks(self.model())}
        for plan in self.qa()['layouts']:
            b=index[plan['block_id']]
            self.assertAlmostEqual(b['font_size'],plan['size'],places=3)
            bounds=b['cell_bbox'] or [40,80,130,85.7]
            self.assertTrue(fitz.Rect(bounds).contains(fitz.Rect(plan['rect'])))
        with fitz.open(self.job/'source.pdf') as src,fitz.open(self.qa()['translated']) as out:
            original=[{k:v for k,v in d.items() if k!='seqno'} for d in src[0].get_drawings()]
            translated=[{k:v for k,v in d.items() if k!='seqno'} for d in out[0].get_drawings()]
            self.assertEqual(original,translated)
            for target in mapping.values():self.assertIn(target,out[0].get_text())

    def test_shrink_limit_does_not_silently_make_body_tiny(self):
        self.make_pdf('Source phrase')
        self.call('import',self.job,self.response('中文短语'))
        self.render()
        for plan in self.qa()['layouts']:self.assertGreaterEqual(plan['size_ratio'],.9)
        self.call('import',self.job,self.response('这是比较长的中文内容。'*8))
        self.render(code=2)
        overflow=next(q for q in self.qa()['blockers'] if q['id'].startswith('overflow-'))
        self.assertGreaterEqual(overflow['details']['minimum_font_size'],11*.9)

    def test_missing_serif_font_is_reported_not_claimed_matched(self):
        block=dict(id='test',spans=[dict(font='Times-Roman',flags=4,text='Body')])
        with patch.object(engine.font_policy,'candidates',return_value=[]):
            _,record=engine.font_policy.Resolver(Namespace()).for_block(block)
        self.assertEqual('fallback',record['selection'])
        self.assertFalse(record['family_match'])

    def test_heiti_family_is_not_confused_with_bold_weight_and_override_is_audited(self):
        span=dict(font='SimHei',flags=0,text='Heading')
        self.assertEqual('sans',engine.font_policy.source_family(dict(spans=[span])))
        self.assertFalse(engine.typography.span_style(span)['bold'])
        self.assertTrue(engine.typography.span_style(dict(span,face_style=dict(bold=True)))['bold'])
        self.make_pdf('Heading')
        b=engine.blocks(self.model())[0]
        file=self.root/'typography.json'
        engine.write_json(file,dict(blocks=[dict(id=b['id'],font_family='sans',bold=True,line_height=13,
                                                reason='测试夹具模拟核对：标题为黑体粗体。')]))
        self.call('typography',self.job,file)
        self.call('import',self.job,self.response('标题'))
        self.render();self.call('verify',self.job)
        self.assertTrue(self.qa()['layouts'][0]['style_default']['bold'])
        self.assertEqual('sans',self.qa()['layouts'][0]['font_policy']['source_family'])
        self.assertIn('reason',engine.blocks(self.model())[0]['typography_overrides'])
        doc=self.model();doc['pages'][0]['blocks'][0]['spans'][0]['flags']|=16
        engine.write_json(self.job/'document.json',doc)
        engine.write_json(file,dict(blocks=[dict(id=b['id'],bold=False,reason='测试夹具：视觉复核为普通字重，修正错误标志。')]))
        self.call('typography',self.job,file);self.render();self.call('verify',self.job)
        self.assertFalse(self.qa()['layouts'][0]['style_default']['bold'])

    def test_paragraph_flow_keeps_font_size_and_adds_english_whitespace(self):
        pdf=fitz.open();p=pdf.new_page(width=350,height=350)
        p.insert_text((40,55),'First paragraph.',fontname='tiro',fontsize=11)
        p.insert_text((40,78),'Second paragraph.',fontname='tiro',fontsize=11)
        pdf.save(self.source);pdf.close()
        self.call('prepare',self.source,'--job',self.job)
        first='这是第一段的完整中文译文，需要比英文更多的行来解释同一内容。'*3
        self.import_all({'First paragraph.':first,'Second paragraph.':'第二段。'})
        self.render(code=2)
        self.call('render',self.job,'--alignment','paragraph','--strict','--dpi',36)
        self.call('verify',self.job)
        qa=self.qa();self.assertEqual('paragraph',qa['alignment'])
        self.assertGreater(qa['paragraph_pairs'][0]['english_blank_pt'],20)
        self.assertTrue(all(p['size_ratio']==1 for p in qa['layouts']))
        with fitz.open(qa['translated']) as out:
            self.assertIn(''.join(first.split()),''.join(out[0].get_text().split()))
            self.assertIn('第二段',out[0].get_text())
        with fitz.open(qa['bilingual']) as out:
            self.assertIn('First paragraph.',out[0].get_text())
            self.assertIn('Second paragraph.',out[0].get_text())
        pair=qa['paragraph_pairs'][1]
        self.assertGreater(pair['top'],qa['paragraph_pairs'][0]['top']+qa['paragraph_pairs'][0]['left_height'])

    def test_paragraph_flow_keeps_dense_table_as_a_whole(self):
        pdf=fitz.open();p=pdf.new_page(width=300,height=300)
        for y in (40,47,54):p.draw_line((40,y),(260,y),width=.2)
        for x in (40,150,260):p.draw_line((x,40),(x,54),width=.2)
        for point,text in [((42,45.5),'Method'),((152,45.5),'Score'),((42,52.5),'Planner'),((152,52.5),'Coder')]:
            p.insert_text(point,text,fontsize=5.1,fontname='tiro')
        pdf.save(self.source);pdf.close();self.call('prepare',self.source,'--job',self.job)
        self.import_all({'Method':'方法','Score':'得分','Planner':'规划器','Coder':'编码器'})
        self.call('render',self.job,'--alignment','paragraph','--strict','--dpi',36)
        self.call('verify',self.job)
        self.assertEqual(1,len(self.qa()['paragraph_pairs']))
        self.assertEqual('visual',self.qa()['paragraph_pairs'][0]['kind'])
        with fitz.open(self.qa()['translated']) as out:
            for text in ('方法','得分','规划器','编码器'):self.assertIn(text,out[0].get_text())
            self.assertEqual(6,len(out[0].get_drawings()))

    def test_visual_region_expansion_persists_and_terminates(self):
        pdf=fitz.open();p=pdf.new_page(width=200,height=200)
        p.draw_rect((30,60,150,65.7))
        p.insert_text((32,64.9),'Stage Packing',fontsize=5.1)
        model=engine.extract_page(p,1)
        boxes=engine.paragraph_layout.visual_regions(p,model)
        self.assertEqual(1,len(boxes))
        self.assertTrue(boxes[0].contains(fitz.Rect(model['blocks'][0]['bbox'])))
        pdf.close()

    def test_wrapping_respects_explicit_breaks_punctuation_and_number_units(self):
        font=fitz.Font(fontfile=r'C:\Windows\Fonts\simsun.ttc')
        text='这是（一个需要适当换行的说明），延迟为 2.5 ns。'
        lines=engine.wrap_text(text,60,font,10)
        self.assertEqual(''.join(text.split()),''.join(''.join(lines).split()))
        self.assertFalse(any(s.startswith(('，','。','）','ns')) or s.endswith('（') for s in lines))
        self.assertIsNone(engine.wrap_text('2.5 ns',10,font,10))
        self.assertEqual(['第一行','第二行'],engine.wrap_text('第一行\n第二行',100,font,10))
        self.assertEqual(['第一行','末。'],engine.wrap_text('第一行\n末。',100,font,10))
        self.assertEqual(['一二三','四五。'],engine.wrap_text('一二三四五。',40,font,10))

    def test_layout_keep_does_not_count_as_finished_translation(self):
        self.make_pdf('Method')
        self.call('import',self.job,self.response('',action='keep',reason='表格字号太小放不下中文。'))
        self.render(code=2)
        q=next(q for q in self.qa()['blockers'] if q['id'].startswith('untranslated-'))
        self.call('decide',self.job,q['id'],'--note','跳过。',code=1)
        self.call('verify',self.job,code=1)

    def test_export_requires_review_and_draft_names_cannot_be_mistaken_for_final(self):
        self.make_pdf('Hello')
        self.call('import',self.job,self.response('你好'))
        self.render()
        dest=self.root/'exports'
        self.call('export',self.job,'--directory',dest,code=1)
        self.call('export',self.job,'--directory',dest,'--draft')
        self.assertTrue((dest/'source__zh-CN__draft__r01.pdf').is_file())
        self.assertTrue(all('__draft__' in p.name for p in dest.iterdir()))
        self.call('verify',self.job,'--visual-reviewed','--note','隔离测试夹具模拟核验，不代表用户文档。')
        self.call('export',self.job,'--directory',dest)
        names={p.name for p in dest.iterdir()}
        self.assertIn('source__zh-CN__r01.pdf',names)
        self.assertIn('source__en-zh-CN__r01.pdf',names)
        self.assertIn('source__review__r01.md',names)
        manifest=engine.read_json(dest/'source__manifest__r01.json')
        for entry in manifest['files']:
            self.assertEqual(entry['sha256'],engine.file_hash(dest/entry['file']))

    def test_export_collision_stale_and_unsafe_names(self):
        self.make_pdf('Hello')
        self.call('import',self.job,self.response('你好'));self.render()
        self.call('verify',self.job,'--visual-reviewed','--note','隔离夹具模拟核验。')
        dest=self.root/'exports'
        self.call('export',self.job,'--directory',dest,'--name','CON.pdf')
        self.assertTrue((dest/'_CON__zh-CN__r01.pdf').is_file())
        self.call('export',self.job,'--directory',dest,'--name','CON.pdf')
        protected=dest/'_CON__zh-CN__r02.pdf';protected.write_bytes(b'prior output')
        self.call('export',self.job,'--directory',dest,'--name','CON.pdf','--revision',2,code=1)
        self.assertEqual(b'prior output',protected.read_bytes())
        self.assertFalse((dest/'_CON__en-zh-CN__r02.pdf').exists())
        self.call('import',self.job,self.response('您好'))
        self.call('export',self.job,'--directory',dest,'--revision',3,code=1)
        safe=engine.deliverables.stem('../../试验:结果?.pdf')
        self.assertNotIn('/',safe);self.assertNotIn(':',safe);self.assertNotIn('?',safe)


if __name__=='__main__':unittest.main()

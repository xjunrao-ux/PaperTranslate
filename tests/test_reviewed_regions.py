"""Regression coverage for whole formulas, tables and zero-height rules."""
import unittest
from unittest.mock import patch
import pymupdf as f
import test_compact_workflow as compact
e=compact.e


class Regions(unittest.TestCase):
    setUp=compact.Compact.setUp
    tearDown=compact.Compact.tearDown
    call=compact.Compact.call
    model=compact.Compact.model
    qa=compact.Compact.qa
    start=compact.Compact.start
    packet=compact.Compact.packet
    apply=compact.Compact.apply

    def test_scientific_notation_stays_on_one_line(self):
        font=f.Font('helv');text='Value 2.333 × 10−4 ends.'
        lines=e.wrap_text(text,75,font,10)
        self.assertTrue(any('2.333 × 10−4' in line for line in lines))

    def test_native_formula_copy_removes_neighbor_ink_and_keeps_original_glyphs(self):
        pdf=f.open();page=pdf.new_page(width=300,height=300)
        page.insert_text((40,89),'Neighbor English words',fontname='tiro',fontsize=10)
        page.insert_text((40,101),'a + b',fontname='tiro',fontsize=10)
        original=page.get_text()
        crop,record=e.content.native_crop(pdf,dict(page=1,bbox=[39,83,99,104],baseline=101,source_size=10))
        self.assertEqual('a + b',crop[0].get_text(clip=f.Rect(39,83,99,104)).strip())
        self.assertGreater(record['neighbor_glyphs_removed'],0)
        self.assertEqual(original,pdf[0].get_text())
        self.assertTrue(any('Nimbus' in x[3] or 'Times' in x[3] for x in crop[0].get_fonts()))
        pdf.close()

    def test_grouped_paragraph_cannot_change_numeric_content_after_registration(self):
        pdf=f.open();p=pdf.new_page(width=400,height=400)
        p.insert_text((40,80),'Value 12 is stable.',fontsize=11);pdf.save(self.source);pdf.close();self.start()
        doc=self.model();block=e.blocks(doc)[0]
        group=dict(id='paragraph1',page=1,bbox=[38,65,200,85],kind='paragraph',source_ids=[block['id']],reason='Checked source paragraph.',translation='数值 12 保持稳定。')
        file=self.root/'regions.json';e.write_json(file,dict(regions=[group]));self.call('regions',self.job,file)
        doc=self.model();doc['reviewed_regions'][0]['translation']='数值 13 保持稳定。'
        with self.assertRaisesRegex(ValueError,'数字发生变化'):e.audit.structure(doc,[],'paired')
        group['translation']='数值 13 保持稳定。';e.write_json(file,dict(regions=[group]))
        self.call('regions',self.job,file,code=1)

    def test_complete_formula_number_and_standalone_footnote_rule_survive(self):
        pdf=f.open();p=pdf.new_page(width=500,height=500)
        p.insert_text((40,80),'Method',fontsize=11)
        p.insert_text((40,150),'a / b = c',fontname='tiro',fontsize=10)
        p.insert_text((440,150),'(1)',fontsize=10)
        p.draw_line((40,420),(140,420),width=.4)
        pdf.save(self.source);pdf.close();self.start()
        doc=self.model();ids=[b['id'] for b in e.blocks(doc) if 100<b['bbox'][1]<160]
        file=self.root/'regions.json'
        e.write_json(file,dict(regions=[dict(id='equation1',page=1,bbox=[38,130,465,155],kind='formula',source_ids=ids,reason='Whole expression and right-aligned equation number verified.')]))
        self.call('regions',self.job,file)
        self.apply(self.packet(),lambda text:'方法')
        self.call('build',self.job,'--dpi',36)
        qa=self.qa();self.assertFalse(qa['blockers'])
        self.assertEqual(len(ids),qa['grouped_source_blocks'])
        self.assertEqual('formula',qa['region_checks'][0]['kind'])
        with f.open(qa['translated']) as result:
            self.assertIn('a / b = c',result[0].get_text())
            self.assertIn('(1)',result[0].get_text())
            self.assertTrue(any(abs(d['rect'].y0-444)<.1 and d['rect'].width==100 for d in result[0].get_drawings()))

    def test_table_label_overlay_retains_values_and_source_columns(self):
        pdf=f.open();p=pdf.new_page(width=500,height=500)
        p.insert_text((40,80),'Method',fontsize=11)
        p.insert_text((60,150),'Parameter',fontsize=10)
        p.insert_text((180,150),'Value',fontsize=10)
        p.insert_text((60,170),'alpha',fontsize=10)
        p.insert_text((180,170),'1.25',fontsize=10)
        p.draw_line((45,135),(235,135));p.draw_line((45,180),(235,180))
        pdf.save(self.source);pdf.close();self.start();doc=self.model()
        ids=[b['id'] for b in e.blocks(doc) if 120<b['bbox'][1]<180]
        labels=[dict(text='参数',bbox=[59,138,110,152],font_size=7.5),dict(text='取值',bbox=[179,138,211,152],font_size=7.5)]
        file=self.root/'regions.json';e.write_json(file,dict(regions=[dict(id='table1',page=1,bbox=[44,134,236,182],kind='table',source_ids=ids,reason='Verified rows and labels.',reviewed=True,labels=labels)]))
        self.call('regions',self.job,file);self.apply(self.packet(),lambda text:'方法')
        candidates=[([[10,10],[70,10],[70,28],[10,28]],'Value',.99)]
        with patch.object(e.media,'recognize',return_value=candidates) as recognize:
            self.call('region-ocr',self.job,'--dpi',180)
            self.assertEqual(2,recognize.call_count)
            self.call('region-ocr',self.job,'--dpi',180)
            self.assertEqual(2,recognize.call_count)
        self.assertTrue(e.read_json(self.job/'region-ocr.json')['review_required'])
        self.call('build',self.job,'--dpi',36);qa=self.qa()
        self.assertFalse(qa['blockers']);self.assertEqual(2,qa['region_checks'][0]['labels'])
        with f.open(qa['translated']) as result:
            text=result[0].get_text();self.assertIn('参数',text);self.assertIn('取值',text);self.assertIn('1.25',text)
        with f.open(qa['bilingual']) as result,f.open(self.source) as source:
            original=source[0].get_pixmap(dpi=72)
            left=result[0].get_pixmap(clip=f.Rect(0,24,500,524),dpi=72)
            self.assertEqual(original.samples,left.samples)


if __name__=='__main__':unittest.main()

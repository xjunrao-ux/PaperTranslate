"""Page fidelity, semantic boundaries and genuine indentation regressions."""
import unittest
import pymupdf as f
import test_workflow as base
e=base.engine


class PageLayout(unittest.TestCase):
    def block(self,text='Body',size=10,box=(40,60,250,90),**extra):
        return dict(id='b',page=1,kind='text',role='paragraph',source=text,font_size=size,bbox=list(box),cell_bbox=None,spans=[dict(text=text,size=size,font='Times-Roman',flags=0)],**extra)

    def test_regular_weight_paper_title_and_letter_heading(self):
        b=self.block('Paper title',22);p=dict(number=1,height=792,blocks=[b])
        self.assertEqual('title',e.profiles.role(b,p,10))
        b=self.block('B. Qualitative Insights');p['blocks']=[b]
        self.assertEqual('subheading',e.profiles.role(b,p,10))

    def test_table_context_precedes_heading_weight(self):
        b=self.block('Average',10,role_override=True);b['role']='heading'
        b['cell_bbox']=[40,60,250,90];p=dict(number=1,height=792,blocks=[b])
        self.assertEqual('table',e.profiles.role(b,p,10))

    def test_real_first_line_indent_preserves_following_line_start(self):
        b=self.block();b['first_line_indent']=2
        text='这是需要首行缩进的中文段落，后续行回到左边界，所有文字必须完整保留。'
        font=f.Font('china-s');styles=[e.typography.default_style(b) for _ in text]
        plan=e.typography.rich_layout(text,styles,f.Rect(40,60,160,260),b,font,10,e.wrap_text)
        self.assertIsNotNone(plan)
        self.assertEqual(60,plan['segments'][0]['x'])
        self.assertEqual(40,next(s for s in plan['segments'] if s['line_index']==1)['x'])
        self.assertEqual(text,''.join(plan['lines']))

    def test_corrupt_font_stream_is_rejected(self):
        doc=f.open();p=doc.new_page();p.insert_text((40,50),'Test')
        xref=p.get_fonts()[0][0];doc.update_object(xref,'<<>>');doc.update_stream(xref,b'q Q')
        with self.assertRaisesRegex(ValueError,'字体资源'):e.audit.resources(doc)
        doc.close()

    def test_merged_heading_is_blocker(self):
        b=self.block('B. Qualitative Insights a) Debugging capabilities: content');b['style_role']='body'
        self.assertTrue(e.audit.structure(dict(pages=[dict(number=1,height=792,blocks=[b])]),[],'position'))

    def test_build_defaults_to_intact_page(self):
        parser=e.parser() if hasattr(e,'parser') else None
        # Register the public command schema directly, without rendering mocks.
        import argparse
        p=argparse.ArgumentParser();e.workflow.register(p.add_subparsers(),e)
        self.assertEqual('paired',p.parse_args(['build','job']).alignment)

    def test_section_heading_is_not_joined_back_to_next_paragraph(self):
        doc=f.open();p=doc.new_page()
        p.insert_text((40,60),'B. Qualitative Insights',fontsize=10)
        p.insert_text((40,72),'a) Debugging capabilities: the agent improves.',fontsize=10)
        model=e.extract_page(p,1,semantic=True)
        self.assertTrue(any(b['source']=='B. Qualitative Insights' for b in model['blocks']))
        self.assertFalse(any('Insights a)' in b['source'] for b in model['blocks']))
        doc.close()

    def test_same_baseline_prose_fragments_are_joined_before_translation(self):
        doc=f.open();p=doc.new_page()
        p.insert_text((40,60),'3) LLM-Powered',fontsize=10)
        p.insert_text((130,60),'Evaluation',fontsize=10)
        p.insert_text((190,60),'Framework:',fontsize=10)
        model=e.extract_page(p,1,semantic=True)
        self.assertTrue(any('3) LLM-Powered Evaluation Framework:'==b['source'] for b in model['blocks']))
        doc.close()


if __name__=='__main__':unittest.main()

"""Shorter source paragraphs receive measured blank space within each column."""
import unittest
import pymupdf as f
import test_compact_workflow as compact
e=compact.e


class Paired(unittest.TestCase):
    setUp=compact.Compact.setUp
    tearDown=compact.Compact.tearDown
    call=compact.Compact.call
    model=compact.Compact.model
    qa=compact.Compact.qa
    start=compact.Compact.start
    packet=compact.Compact.packet
    apply=compact.Compact.apply

    def test_five_vs_eight_lines_adds_three_lines_without_flattening_columns(self):
        def row(y,h,lane):
            return dict(rect=f.Rect(40 if lane=='left' else 330,y,250 if lane=='left' else 540,y+50),height=h,body=True,gap=0)
        a=row(60,80,'left');b=row(120,50,'left');c=row(60,50,'right');d=row(120,50,'right')
        self.assertTrue(e.paired_layout.arrange([a,b,c,d],612))
        self.assertEqual(150,b['top']);self.assertEqual(120,d['top'])
        self.assertEqual(30,a['height']-a['rect'].height)
        self.assertEqual(330,c['rect'].x0)

    def test_spanning_figure_waits_for_both_columns(self):
        rows=[dict(rect=f.Rect(40,60,250,110),height=100,body=True),
              dict(rect=f.Rect(330,60,540,110),height=50,body=True),
              dict(rect=f.Rect(40,130,550,180),height=50,body=False)]
        e.paired_layout.arrange(rows,612)
        self.assertEqual('span',rows[2]['lane']);self.assertEqual(180,rows[2]['top'])

    def test_source_spacing_does_not_inherit_chinese_gap_or_slight_midline_overlap(self):
        rows=[dict(rect=f.Rect(37,70,285,120),height=50,body=True,gap=9),
              dict(rect=f.Rect(37,125,285,175),height=50,body=True,gap=9),
              dict(rect=f.Rect(303,70,558,120),height=50,body=True),
              dict(rect=f.Rect(297.32,180,550,360),height=180,body=False)]
        self.assertTrue(e.paired_layout.arrange(rows,595.276))
        self.assertEqual(125,rows[1]['top'])
        self.assertEqual('right',rows[3]['lane'])
        self.assertEqual([(0.,842,0.)],e.paired_layout.strips(rows,595.276,842,'left'))

    def test_source_registry_rejects_deleted_blocks_even_if_regions_are_reregistered(self):
        pdf=f.open();p=pdf.new_page();p.insert_text((40,80),'First paragraph.')
        p.insert_text((40,180),'Second paragraph.');pdf.save(self.source);pdf.close();self.start()
        doc=self.model();self.assertEqual(2,len(doc['source_registry']))
        doc['pages'][0]['blocks'].pop();e.write_json(self.job/'document.json',doc)
        with self.assertRaisesRegex(ValueError,'删除|改写'):e.audit.structure(doc,[],'paired')
        file=self.root/'regions.json';e.write_json(file,dict(regions=[]))
        self.call('regions',self.job,file,code=1)

    def test_footer_and_footnote_use_small_type_without_indent(self):
        pdf=f.open();p=pdf.new_page(width=595,height=842)
        p.insert_text((40,80),'Ordinary body paragraph has enough words for source classification.',fontsize=10)
        p.insert_text((305,730),'1 Footnote text explains the data.',fontsize=9)
        p.insert_text((420,780),'Article number, page 1 of 22',fontsize=9)
        pdf.save(self.source);pdf.close();self.start();doc=self.model()
        roles={b['style_role']:b for b in e.blocks(doc)}
        for role in ('footnote','footer'):
            b=e.profiles.render_block(roles[role],doc)
            self.assertEqual(7.5,b['font_size']);self.assertEqual(0,b['first_line_indent'])
        self.assertEqual('right',e.profiles.render_block(roles['footer'],doc)['align'])

    def test_build_keeps_two_columns_and_aligns_following_pair(self):
        doc=f.open();p=doc.new_page(width=612,height=792)
        p.insert_text((40,80),['First English paragraph has several words.']*5,fontsize=10,fontname='tiro')
        p.insert_text((40,180),'Next English paragraph remains aligned.',fontsize=10,fontname='tiro')
        p.insert_text((330,80),['Right column has its own paragraph.']*3,fontsize=10,fontname='tiro')
        p.insert_text((330,160),'Next right paragraph stays in its column.',fontsize=10,fontname='tiro')
        doc.save(self.source);doc.close();self.start()
        self.apply(self.packet(),lambda s:('这段中文需要更多行用于完整表达内容，较短的英文段落下方应该补足留白，使下一段起点一致。'*5 if s.startswith('First') else '这是其他对应段落的中文译文。'))
        self.call('build',self.job,'--dpi',36)
        q=self.qa();self.assertEqual('paired',q['alignment']);self.assertFalse(q['blockers'])
        pairs=q['paragraph_pairs'];left=sorted([p for p in pairs if p['lane']=='left'],key=lambda p:p['top'])
        self.assertTrue(all(p['two_columns'] for p in pairs))
        self.assertGreater(left[0]['english_blank_pt'],0)
        self.assertGreater(left[1]['top'],180)
        self.assertTrue(any(p['lane']=='right' and p['mono_x']>=330 for p in pairs))
        self.assertTrue(all(p['left_rect'][1]==p['top'] for p in pairs))
        self.assertTrue(all('\n\n' not in v.get('text','') for v in e.read_json(self.job/'translations.json').values()))


if __name__=='__main__':unittest.main()

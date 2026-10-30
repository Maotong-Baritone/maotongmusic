import copy
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tools.validate_literature import validate

ROOT=Path(__file__).resolve().parents[1]


class LiteratureDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=json.loads((ROOT/'literature.json').read_text(encoding='utf-8'))

    def test_catalog_is_valid_and_subjects_are_independent_from_document_type(self):
        self.assertEqual(validate(self.data),[])
        expected={'musicology','theory','performance','aesthetics','composer-studies','language','technology','reference'}
        self.assertTrue(expected <= {v['id'] for v in self.data['subjects']})
        self.assertNotIn('translation',{v['id'] for v in self.data['subjects']})

    def test_rejects_unknown_subject_duplicate_file_and_invalid_page(self):
        if not self.data['documents']:self.skipTest('No published documents')
        for mutation in [lambda d:d['documents'][0]['subjects'].append('not-a-subject'),
                         lambda d:d['documents'].append(copy.deepcopy(d['documents'][0])),
                         lambda d:d['documents'][0]['contents'].append({'title':'bad','pdf_page':0}),
                         lambda d:d['documents'][0].update(storage_key='../private.pdf')]:
            sample=copy.deepcopy(self.data);mutation(sample);self.assertTrue(validate(sample))

    def test_author_and_translator_labels_cannot_disagree_for_same_person(self):
        if not self.data['documents']:self.skipTest('No published documents')
        sample=copy.deepcopy(self.data);person=sample['documents'][0]['authors'][0]
        sample['documents'][0]['translators'].append({'id':person['id'],'name':'Different person label'})
        self.assertTrue(validate(sample))

    def test_unverified_bibliography_uses_null_and_rejects_invalid_values(self):
        sample=copy.deepcopy(self.data)
        sample['documents'][0].update(year=None,publisher=None)
        self.assertEqual(validate(sample),[])
        for year in ['', '2012', 0, True, 2101]:
            bad=copy.deepcopy(sample);bad['documents'][0]['year']=year
            self.assertTrue(validate(bad))
        for publisher in ['', ' ', False, []]:
            bad=copy.deepcopy(sample);bad['documents'][0]['publisher']=publisher
            self.assertTrue(validate(bad))


@unittest.skipUnless(shutil.which('node'),'Node.js required for literature behavior')
class LiteratureBehaviorTest(unittest.TestCase):
    def run_js(self,script):
        prelude=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context=vm.createContext({URL,window:{location:{href:'https://example.test/library/literature.html'},addEventListener(){}}});
vm.runInContext(fs.readFileSync('js/literature.js','utf8'),context);
const data=JSON.parse(fs.readFileSync('literature.json','utf8'));
context.data=data;
vm.runInContext("literatureCatalog=data;literatureBaseUrl='https://scores.maotong.me'",context);
const blank={q:'',subject:'',type:'',author:'',language:'',tag:'',composer:''};
const filter=state=>context.filterLiterature(data.documents,{...blank,...state});
"""
        result=subprocess.run(['node','-e',prelude+script],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr or result.stdout)

    def test_multisubject_does_not_duplicate_records_and_composer_is_not_author(self):
        self.run_js(r"""
const book=data.documents.find(d=>d.work_id==='adorno-wagner-mahler');
assert(book);
assert(filter({subject:'musicology'}).some(d=>d.id===book.id));
assert(filter({subject:'aesthetics'}).some(d=>d.id===book.id));
assert.equal(new Set(filter({}).map(d=>d.id)).size,data.documents.length);
assert(filter({composer:'richard-wagner'}).some(d=>d.id===book.id));
assert(!filter({author:'richard-wagner'}).some(d=>d.id===book.id));
assert(!filter({author:'peng-bei'}).some(d=>d.id===book.id));
assert(filter({q:'彭蓓'}).some(d=>d.id===book.id));
assert.equal(filter({subject:'theory',language:'汉语'}).length,0);
""")

    def test_lyric_translations_do_not_turn_whole_book_into_translation(self):
        self.run_js(r"""
const book=data.documents.find(d=>d.work_id==='interpretation-french-song');
assert.equal(book.is_translation,false);
assert.equal(book.translators[0].role,'歌词英译');
assert(filter({q:'Winifred Radford'}).some(d=>d.id===book.id));
const card=context.literatureCard(book);assert(!card.includes('>译本</span>'));
assert(card.includes('data-document-id='));
assert(card.includes('target="_blank"'));
""")

    def test_addressable_filters_safe_pdf_paths_and_escaped_metadata(self):
        self.run_js(r"""
const state=context.literatureState('https://example.test/library/literature.html?subject=theory&q=harmony&composer=richard-wagner');
assert.equal(state.subject,'theory');assert.equal(state.q,'harmony');
const link=context.literatureUrl({author:'pierre-bernac'},true);
assert.equal(link.pathname,'/library/literature.html');assert.equal(link.searchParams.get('author'),'pierre-bernac');
assert.equal(link.searchParams.has('subject'),false);
assert.equal(context.literaturePdfUrl({storage_key:'../private.pdf'}),'');
assert(context.literaturePdfUrl(data.documents[0]).startsWith('https://scores.maotong.me/literature/'));
const malicious={...data.documents[0],title:'<img src=x onerror=alert(1)>',summary:'<script>bad()</script>'};
const html=context.literatureCard(malicious);assert(!html.includes('<script>'));assert(!html.includes('<img src=x'));
assert(html.includes('&lt;script&gt;'));
""")

    def test_unverified_bibliography_is_explicit_in_cards_and_details(self):
        self.run_js(r"""
const book={...data.documents[0],publisher:null,year:null};
const card=context.literatureCard(book);
assert(card.includes('出版机构未核'));assert(card.includes('年份未核'));
assert(!card.includes('null'));assert(!card.includes('undefined'));
const elements=new Map();
context.document={title:'',getElementById(id){
 if(!elements.has(id))elements.set(id,{innerHTML:'',open:false,showModal(){this.open=true;}});
 return elements.get(id);
}};
context.book=book;vm.runInContext('literatureCatalog={...literatureCatalog,documents:[book]}',context);
context.showLiteratureDetail(book.id);
const detail=elements.get('literatureDetailBody').innerHTML;
assert(detail.includes('<dt>出版机构</dt><dd>未核</dd>'));
assert(detail.includes('<dt>出版年份</dt><dd>未核</dd>'));
""")


if __name__=='__main__':unittest.main()

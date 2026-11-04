from __future__ import annotations

import shutil
import subprocess
import unittest

from test_composer_navigation import PRELUDE, ROOT


@unittest.skipUnless(shutil.which('node'), 'Node.js is needed for catalog search checks')
class CatalogSearchTest(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run(
            ['node', '-e', PRELUDE + script], cwd=ROOT,
            capture_output=True, text=True, encoding='utf-8',
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_catalog_numbers_ignore_description_and_require_full_number(self):
        self.run_js(r"""
for (const query of ['Op. 116', 'op116', 'OPUS 116', 'Ｏｐ．１１６']) {
 assert(context.matchesSearch({title:'7 Fantasien, Op. 116'}, query));
 assert(!context.matchesSearch({title:'Op. 1160'}, query));
 assert(!context.matchesSearch({title:'Op. 116a'}, query));
 assert(!context.matchesSearch({title:'Op. 68',description:'Op. 116; pp. 116; IMSLP #116'}, query));
}
assert(context.matchesSearch({title:'Symphony K. 550'}, 'KV550'));
assert(!context.matchesSearch({title:'Song D. 3280'}, 'D328'));
assert(context.matchesSearch({title:'No. 1 Capriccio, Op. 116',composer:'Johannes Brahms/勃拉姆斯'}, 'Brahms Op116 No1'));
assert(!context.matchesSearch({title:'No. 10 Capriccio, Op. 116',composer:'Johannes Brahms/勃拉姆斯'}, 'Brahms Op116 No1'));
""")

    def test_delisted_instrumental_op116_is_absent_from_catalog_search(self):
        self.run_js(r"""
const hits = catalog.filter(item => context.matchesSearch(item, 'Op. 116'));
assert.equal(hits.length, 0);
""")

    def test_title_beats_description_and_explicit_date_sort_still_works(self):
        self.run_js(r"""
const fixture = [
 {id:1,title:'Other song',description:'Winterreise',date:'2026-11-03'},
 {id:2,title:'Winterreise',date:'2020-01-01'},
 {id:3,title:'A song',work:'Winterreise',date:'2025-01-01'}
].map(item=>({...item,composer:'Franz Schubert/舒伯特',category:'艺术歌曲',filename:'fixture.pdf'}));
context.fixture=fixture;evaluate('musicData=fixture;initComposerDirectory(musicData);filters.search="Winterreise";currentPage=8;');
element('searchInput').value='Winterreise';element('sortSelect').value='relevance';
context.performSearch();
assert.equal(evaluate('currentPage'),1);
assert.equal(element('filteredCount').innerText,'3 份乐谱资料');
assert(element('mainTableBody').innerHTML.indexOf("openDetail('2')") < element('mainTableBody').innerHTML.indexOf("openDetail('3')"));
assert(element('mainTableBody').innerHTML.indexOf("openDetail('3')") < element('mainTableBody').innerHTML.indexOf("openDetail('1')"));
element('sortSelect').value='date_desc';context.applyFilters();
assert(element('mainTableBody').innerHTML.indexOf("openDetail('1')") < element('mainTableBody').innerHTML.indexOf("openDetail('2')"));
""")

    def test_voice_aliases_are_bidirectional_without_collapsing_voice_families(self):
        self.run_js(r"""
for(const query of ['女中音','次女高音','Mezzo','Mezzo-Soprano','Mezzo Soprano']) {
 for(const voice of ['女中音','Mezzo-soprano/次女高音','Mezzo Soprano/次女高音','女高音、女中音、钢琴']) {
  assert(context.matchesVoiceType(voice,query), voice+' / '+query);
 }
 assert(!context.matchesVoiceType('Soprano/女高音',query));
 assert(!context.matchesVoiceType('高声部、钢琴',query));
}
assert.equal(context.normalizeVoiceType('Mezzo-soprano/次女高音'),'女中音');
assert(!context.matchesVoiceType('Mezzo-soprano/次女高音','女高音'));
assert(!context.matchesVoiceType('Bass-Baritone/低男中音','男中音'));
assert(context.matchesVoiceType('Bass-Baritone / Baritone','男中音'));
assert(!context.matchesVoiceType('CounterTenor','Tenor'));
assert(context.matchesVoiceType('小提琴、钢琴','小提琴'));
const before=JSON.stringify(catalog);
catalog.forEach(item=>context.normalizeVoiceType(item.voice_types));
assert.equal(JSON.stringify(catalog),before);
evaluate('currentPage=8');element('voiceInput').value='女中音';context.applyFilters();
assert.equal(evaluate('currentPage'),1);
""")

    def test_search_keeps_accents_contractions_typos_and_numeric_boundaries(self):
        self.run_js(r"""
assert(context.matchesSearch({title:'Après un rêve'}, 'apres un reve'));
assert(context.matchesSearch({title:'Dagli immortali'}, "Dagl'immortali"));
assert(context.matchesSearch({title:'Winterreise'}, 'Winterreize'));
assert(context.matchesSearch({title:'Lyric Pieces'}, 'Lyric Pieces'));
assert(context.matchesSearch({title:'Aria for Soprano'}, 'Soprano'));
assert(!context.matchesSearch({title:'No. 10 Song'}, 'No. 1'));
assert(!context.matchesSearch({title:'Song'}, '...'));
assert(!context.matchesSearch({title:'Song'}, ''));
assert(!context.matchesSearch({title:'Song',description:'https://example.test/Winterreise'}, 'Winterreise'));
assert(context.matchesSearch({title:'Song',description:'https://example.test/Winterreise；版本：Peters'}, 'Peters'));
""")


if __name__ == '__main__':
    unittest.main()

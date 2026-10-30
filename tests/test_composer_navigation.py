from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {value:'', innerHTML:'', innerText:'', hidden:false, style:{}, dataset:{},
    classList:{add(){},remove(){},toggle(){},contains(){return false;}},
    scrollIntoView(){},addEventListener(){},replaceChildren(){},querySelector(){return null;}});
  return elements.get(id);
}
element('languageSelect').value='all'; element('sortSelect').value='date_desc';
const events = new Map();
const location = {href:'https://example.test/library/'};
const history = {state:null, entries:[],
  replaceState(state,unused,url){this.state=state;location.href=new URL(url,location.href).href;},
  pushState(state,unused,url){this.entries.push({state:this.state,url:location.href});this.state=state;location.href=new URL(url,location.href).href;}};
const context = {URL,URLSearchParams,console,Map,Set,Option:class{},location,history,
  document:{title:'曲库',getElementById:element,querySelectorAll(){return[];},addEventListener(){}},
  localStorage:{getItem(){return null;},setItem(){},removeItem(){}},
  addEventListener(name,callback){events.set(name,callback);},
  bootstrap:{Modal:{getInstance(){return null;}}}};
context.window=context;
vm.createContext(context);
vm.runInContext(fs.readFileSync('js/app.js','utf8'),context);
const catalog=JSON.parse(fs.readFileSync('data.json','utf8'));
context.catalog=catalog;
vm.runInContext('musicData=catalog;initComposerDirectory(musicData);',context);
function evaluate(source){return vm.runInContext(source,context);}
"""


@unittest.skipUnless(shutil.which('node'), 'Node.js is needed for composer navigation checks')
class ComposerNavigationTest(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run(['node', '-e', PRELUDE + script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_catalog_aliases_share_identity_and_display(self):
        self.run_js(r"""
const pairs=[['Christoph Gluck / 格鲁克','Christoph Willibald Gluck/格鲁克'],
 ['Domenico Gaetano Donizetti/多尼采蒂','Gaetano Donizetti/多尼采蒂'],
 ['Erich Korngold/科恩戈尔德','Erich Wolfgang Korngold/科恩戈尔德'],
 ['Giaochino Rossini','Gioachino Rossini/罗西尼'],
 ['Henry Purcell/普塞尔','Henry Purcell/普赛尔'],
 ['Jules Massenet/儒勒 马斯内','Jules Massenet/马斯奈'],
 ['Ruggero Leoncavallo/莱翁卡瓦洛','Ruggero Leoncavallo/莱昂卡瓦洛'],
 ['Vincenzo Bellini/贝里尼','Vincenzo Bellini/贝利尼']];
for(const [a,b] of pairs){
 assert.equal(context.composerIdsFor(a)[0],context.composerIdsFor(b)[0]);
 assert.equal(context.composerDisplayName(a),context.composerDisplayName(b));
}
assert.equal(context.exactComposer('Ｄｖｏｒａｋ').id,context.exactComposer('德沃夏克').id);
assert.equal(context.exactComposer('J. S. Bach').id,context.exactComposer('Johann Sebastian Bach').id);
assert.equal(context.exactComposer('Bjo\u0308rn Ulvaeus').id,context.exactComposer('Björn Ulvaeus').id);
assert.notEqual(context.exactComposer('Richard Strauss').id,context.exactComposer('Johann Strauß II').id);
assert.equal(context.exactComposer('Strauss'),null);
assert(!context.composerSearchText('Johann Strauss II/小约翰·施特劳斯').includes('Richard'));
assert.deepEqual(Array.from(context.composerIdsFor('ABRSM')),[]);
assert.deepEqual(Array.from(context.composerIdsFor('未署名（待核）')),[]);
assert.deepEqual(Array.from(context.composerIdsFor('姜夔 / 罗忠镕（配伴奏）')),['姜夔']);
""")

    def test_click_clears_previous_limits_and_contains_all_versions(self):
        self.run_js(r"""
evaluate("filters.search='unrelated';filters.category='音乐剧选段';filters.favoritesOnly=true;currentPage=8;");
element('searchInput').value='unrelated';element('languageSelect').value='英语';element('voiceInput').value='男低音';
context.navigateToComposer(context.exactComposer('多尼采蒂').id);
assert.equal(element('filteredCount').innerText,catalog.filter(r=>r.composer.split('、').some(name=>['Gaetano Donizetti/多尼采蒂','Domenico Gaetano Donizetti/多尼采蒂'].includes(name.trim()))).length+' 首乐谱');
assert.equal(element('searchInput').value,'');assert.equal(element('voiceInput').value,'');
assert.equal(element('languageSelect').value,'all');
assert.equal(evaluate('filters.category'),'all');assert.equal(evaluate('filters.favoritesOnly'),false);
assert.equal(evaluate('currentPage'),1);
assert.equal(new URL(location.href).searchParams.get('composer'),'gaetano-donizetti');
assert.equal(new URL(location.href).hash,'#mainContentArea');
assert(element('mainTableBody').innerHTML.includes('data-composer-id="gaetano-donizetti"'));
assert(element('mobileScoreList').innerHTML.includes('data-composer-id="gaetano-donizetti"'));
assert(element('listTitle').innerText.includes('多尼采蒂'));
context.navigateToComposer(context.exactComposer('Richard Strauss').id);
assert.equal(element('filteredCount').innerText,catalog.filter(r=>r.composer==='Richard Strauss/理查·施特劳斯').length+' 首乐谱');
context.navigateToComposer(context.exactComposer('Johann Strauss II').id);
assert.equal(element('filteredCount').innerText,catalog.filter(r=>r.composer==='Johann Strauss II/小约翰·施特劳斯').length+' 首乐谱');
context.navigateToComposer(context.exactComposer('Benny Andersson').id);
assert.equal(element('filteredCount').innerText,catalog.filter(r=>['Benny Andersson','Benny Andersson、Björn Ulvaeus'].includes(r.composer)).length+' 首乐谱');
context.navigateToComposer(context.exactComposer('Björn Ulvaeus').id);
assert.equal(element('filteredCount').innerText,catalog.filter(r=>['Björn Ulvaeus','Benny Andersson、Björn Ulvaeus'].includes(r.composer)).length+' 首乐谱');
element('composerInput').value='';context.applyFilters();
assert.equal(element('filteredCount').innerText,catalog.length+' 首乐谱');
assert.equal(new URL(location.href).searchParams.has('composer'),false);
""")

    def test_profile_refresh_history_and_safe_links(self):
        self.run_js(r"""
location.href='https://example.test/library/?composer=gioachino-rossini#mainContentArea';
context.restoreLibraryView();context.applyFilters();
const rossiniCount=catalog.filter(r=>r.composer.split('、').some(name=>['Gioachino Rossini/罗西尼','Giaochino Rossini'].includes(name.trim()))).length+' 首乐谱';
assert.equal(element('filteredCount').innerText,rossiniCount);
evaluate('currentPage=2;');context.saveLibraryViewToHistory();const saved=history.state.libraryView;
context.navigateToComposer(context.exactComposer('贝多芬').id);
context.restoreLibraryView(saved);context.applyFilters();
assert.equal(evaluate('currentPage'),2);assert.equal(element('filteredCount').innerText,rossiniCount);
location.href='https://example.test/library/?composer=no-such-person';context.restoreLibraryView();context.applyFilters();
assert.equal(element('filteredCount').innerText,'0 首乐谱');
const links=context.renderComposerLinks('Benny Andersson、Björn Ulvaeus');
assert.equal((links.match(/data-composer-id=/g)||[]).length,2);
assert(!context.renderComposerLinks('ABRSM').includes('<a'));
assert.equal(context.renderComposerLinks('<img src=x onerror=alert(1)>'),'&lt;img src=x onerror=alert(1)&gt;');
assert(!context.renderComposerLinks('姜夔 / 罗忠镕（配伴奏）').includes('data-composer-id="罗忠镕"'));
location.href='https://example.test/library/?score=old';
assert.equal(new URL(context.composerUrlFor('gioachino-rossini')).searchParams.has('score'),false);
""")

    def test_collection_is_listed_for_each_credited_composer_and_alias(self):
        self.run_js(r"""
const collection={id:-1,public_id:'00000000-0000-4000-8000-000000000001',title:'Three-composer collection fixture',
 composer:'Giaochino Rossini、Domenico Gaetano Donizetti/多尼采蒂、Vincenzo Bellini/贝里尼',
 category:'乐谱书/曲集',voice_types:'声乐、钢琴',language:'意大利语',filename:'fixture.pdf',date:'2026-10-29'};
catalog.push(collection);evaluate('initComposerDirectory(musicData)');
for(const name of ['罗西尼','多尼采蒂','贝利尼']){
 context.navigateToComposer(context.exactComposer(name).id);
 assert(element('mainTableBody').innerHTML.includes(collection.title));
 assert(element('mobileScoreList').innerHTML.includes(collection.title));
}
context.navigateToComposer(context.exactComposer('普契尼').id);
assert(!element('mainTableBody').innerHTML.includes(collection.title));
assert.equal((context.renderComposerLinks(collection.composer).match(/data-composer-id=/g)||[]).length,3);
""")


if __name__ == '__main__':
    unittest.main()

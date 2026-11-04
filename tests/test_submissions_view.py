from __future__ import annotations

import shutil
import subprocess
import unittest

from test_composer_navigation import PRELUDE, ROOT


@unittest.skipUnless(shutil.which('node'), 'Node.js is needed for submissions navigation checks')
class SubmissionsViewTest(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run(['node', '-e', PRELUDE + script], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_route_shows_only_credited_scores_on_desktop_and_mobile(self):
        self.run_js(r'''
location.href='https://example.test/library/?view=submissions#mainContentArea';
context.restoreLibraryView();context.applyFilters();
const credited=catalog.filter(item=>typeof item.submitter_name==='string'&&item.submitter_name.trim());
assert(credited.length>0);
assert.equal(element('filteredCount').innerText,credited.length+' 份乐谱资料');
for(const id of ['mainTableBody','mobileScoreList']) {
 for(const score of credited) assert(element(id).innerHTML.includes(context.escapeHtml(score.title)),score.title);
 assert(!element(id).innerHTML.includes(context.escapeHtml(catalog.find(item=>!item.submitter_name).title)));
 assert(element(id).innerHTML.includes('投稿：'));
}
assert.equal(element('listTitle').innerText,'🤝 用户投稿');
assert.equal(element('submissionViewNotice').hidden,false);
assert.equal(element('recentSection').style.display,'none');
assert.equal(element('submissionsNav').attributes['aria-current'],'page');
assert.equal(element('libraryNav').attributes['aria-current'],undefined);
assert(context.document.title.startsWith('用户投稿 |'));
''')

    def test_search_and_facets_stay_inside_contributions_when_cleared(self):
        self.run_js(r'''
context.fixture=[
 {id:1,title:'Shared song',composer:'A composer',category:'艺术歌曲',language:'法语',voice_types:'男中音',submitter_name:'昵称'},
 {id:2,title:'Shared collection',composer:'B composer',category:'声乐套曲',language:'意大利语',submitter_name:'另一位'},
 {id:3,title:'Shared song uncredited',composer:'A composer',category:'艺术歌曲',language:'法语'},
 {id:4,title:'Blank credit',composer:'A composer',category:'艺术歌曲',submitter_name:'  '},
 {id:5,title:'Invalid credit',composer:'A composer',category:'艺术歌曲',submitter_name:{name:'unexpected'}}
];
evaluate('musicData=fixture;initComposerDirectory(musicData)');
context.navigateLibraryView('submissions');
assert.equal(element('filteredCount').innerText,'2 份乐谱资料');
element('searchInput').value='Shared song';context.performSearch();
assert.equal(element('filteredCount').innerText,'1 份乐谱资料');
assert(element('listTitle').innerText.includes('用户投稿'));
element('languageSelect').value='意大利语';context.applyFilters();
assert.equal(element('filteredCount').innerText,'0 份乐谱资料');
context.handleFilterReset();
assert.equal(element('searchInput').value,'Shared song');
assert.equal(element('filteredCount').innerText,'1 份乐谱资料');
context.handleFilterReset();
assert.equal(element('searchInput').value,'');
assert.equal(element('filteredCount').innerText,'2 份乐谱资料');
context.filterCategory('声乐套曲');
assert.equal(element('filteredCount').innerText,'1 份乐谱资料');
context.removeActiveFilter('category');
assert.equal(element('filteredCount').innerText,'2 份乐谱资料');
assert.equal(new URL(location.href).searchParams.get('view'),'submissions');
''')

    def test_navigation_history_detail_links_and_other_views(self):
        self.run_js(r'''
context.initDetailNavigation();
context.navigateLibraryView('submissions');
element('languageSelect').value='法语';context.applyFilters();
const count=element('filteredCount').innerText;
const shared=catalog.find(item=>item.submitter_name);
assert.equal(new URL(context.detailUrlFor(context.getStableId(shared))).searchParams.get('view'),'submissions');
assert.equal(new URL(context.composerUrlFor(context.exactComposer('马斯奈').id)).searchParams.has('view'),false);
context.navigateLibraryView('all');
assert.equal(element('filteredCount').innerText,catalog.length+' 份乐谱资料');
assert.equal(element('submissionViewNotice').hidden,true);
const back=history.entries.pop();location.href=back.url;history.state=back.state;
events.get('popstate')({state:back.state});
assert.equal(element('filteredCount').innerText,count);
assert.equal(element('languageSelect').value,'法语');
assert.equal(evaluate('filters.submissionsOnly'),true);
context.navigateToComposer(context.exactComposer('马斯奈').id);
assert.equal(evaluate('filters.submissionsOnly'),false);
assert.equal(new URL(location.href).searchParams.has('view'),false);
context.navigateLibraryView('submissions');context.showFavorites();
assert.equal(evaluate('filters.submissionsOnly'),false);
assert.equal(evaluate('filters.favoritesOnly'),true);
assert.equal(new URL(location.href).searchParams.has('view'),false);
const before=location.href;
context.navigateLibraryView('submissions',{ctrlKey:true,preventDefault(){throw Error('modified click intercepted');}});
assert.equal(location.href,before);
''')

    def test_empty_and_unknown_routes(self):
        self.run_js(r'''
evaluate('musicData=[]');context.navigateLibraryView('submissions');
assert.equal(element('filteredCount').innerText,'0 份乐谱资料');
assert(element('noResult').innerHTML.includes('暂无已收录的用户投稿'));
location.href='https://example.test/library/?view=unknown';
context.restoreLibraryView();context.applyFilters();
assert.equal(evaluate('filters.submissionsOnly'),false);
''')


if __name__ == '__main__':
    unittest.main()

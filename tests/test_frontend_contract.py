from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.resources_html = (ROOT / "resources.html").read_text(encoding="utf-8")
        cls.contact_html = (ROOT / "contact.html").read_text(encoding="utf-8")
        cls.resources_js = (ROOT / "js" / "resources.js").read_text(encoding="utf-8")
        cls.resources_data = (ROOT / "js" / "resources-data.js").read_text(encoding="utf-8")
        cls.app_js = (ROOT / "js" / "app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "css" / "style.css").read_text(encoding="utf-8")
        cls.site_config = (ROOT / "site-config.json").read_text(encoding="utf-8")
        cls.catalog = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))

    def test_pdf_preview_is_explicit_and_starts_blank(self):
        self.assertIn('id="mPreview" src="about:blank"', self.index_html)
        self.assertIn('id="btnLoadPreview"', self.index_html)
        self.assertIn("preview.contentWindow.location.replace(currentPdfUrl)", self.app_js)
        self.assertIn("delete preview.dataset.loadedUrl", self.app_js)

    def test_touch_pdf_preview_is_vertically_scrollable(self):
        self.assertIn('id="mobilePdfPreview"', self.index_html)
        self.assertIn("shouldUseTouchPdfPreview()", self.app_js)
        self.assertIn("pdfjs-dist@${PDFJS_VERSION}", self.app_js)
        self.assertIn("touch-action: pan-y pinch-zoom", self.styles)
        self.assertIn("-webkit-overflow-scrolling: touch", self.styles)

    def test_mobile_catalog_has_its_own_card_surface(self):
        self.assertIn('id="mobileScoreList"', self.index_html)
        self.assertIn("mobileHtml +=", self.app_js)
        self.assertIn(".mobile-score-card", self.styles)
        self.assertNotIn('<tr onclick="openDetail', self.app_js)

    def test_detail_links_are_addressable_and_follow_history(self):
        self.assertIn("url.searchParams.set('score', id)", self.app_js)
        self.assertIn("window.addEventListener('popstate'", self.app_js)
        self.assertIn("openDetailFromUrl()", self.app_js)

    def test_favorite_controls_expose_toggle_state(self):
        self.assertIn('data-favorite-id=', self.app_js)
        self.assertIn('aria-pressed=', self.app_js)
        self.assertIn("button.setAttribute('aria-pressed'", self.app_js)

    def test_score_urls_are_built_through_storage_config(self):
        self.assertIn("fetch('site-config.json'", self.app_js)
        self.assertIn("function buildScoreUrl(item)", self.app_js)
        self.assertIn("const pdfUrl = buildScoreUrl(item)", self.app_js)
        self.assertNotIn("const pdfUrl = `scores/${encodedFilename}`", self.app_js)
        self.assertIn('"keyStrategy": "public_id_sharded"', self.site_config)
        self.assertIn('"baseUrl": "https://', self.site_config)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for URL behavior checks')
    def test_preview_cache_version_preserves_pdf_identity_and_download_url(self):
        script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('js/app.js', 'utf8').split('function loadStoredFavorites()')[0];
const context = vm.createContext({ URL, Set, document: {title: '', baseURI: 'https://maotong.me/maotongmusic/'}, loadStoredFavorites: () => new Set() });
vm.runInContext(source, context);
context.configureScoreStorage({baseUrl: 'https://scores.maotong.me', keyStrategy: 'public_id_sharded'});
const item = {public_id: '3dbd97f7-4aff-4db1-a616-ef81161e9748'};
const download = context.buildScoreUrl(item);
const preview = new URL(context.buildScorePreviewUrl(item));
assert.equal(preview.origin + preview.pathname, download);
assert.equal(preview.searchParams.get('preview'), 'cors-1');
assert.equal(preview.hash, '#view=FitH');
assert.equal(context.buildScoreUrl(item), download);
assert.equal(context.buildScorePreviewUrl({}), '');
context.configureScoreStorage({});
const local = new URL(context.buildScorePreviewUrl({filename: '艺术歌曲/a b.pdf'}));
assert.equal(decodeURI(local.pathname), '/maotongmusic/scores/艺术歌曲/a b.pdf');
assert.equal(local.origin, 'https://maotong.me');
"""
        subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True, text=True)

    def test_no_lyrics_is_not_offered_as_a_language_filter(self):
        self.assertIn("l && l !== '无歌词'", self.app_js)

    def test_professional_resources_have_a_dedicated_page(self):
        self.assertIn('href="resources.html"', self.index_html)
        self.assertIn('href="resources.html"', self.contact_html)
        self.assertNotIn('🌍 常用链接', self.index_html)
        self.assertIn('id="resourceSearch"', self.resources_html)
        self.assertIn('id="resourceFilters"', self.resources_html)
        self.assertIn('target="_blank" rel="noopener noreferrer"', self.resources_js)
        self.assertGreaterEqual(self.resources_data.count("url: 'https://"), 42)
        self.assertIn("url: 'https://theoperadatabase.com/'", self.resources_data)
        self.assertIn("url: 'https://accnote.com/'", self.resources_data)
        self.assertIn("const usageOrder =", self.resources_js)
        self.assertIn('class="resource-group"', self.resources_js)
        self.assertIn("['全部', '表演', '创作与理论', '研究', '教育', '职业']", self.resources_js)

    def test_catalog_uses_only_supported_language_labels(self):
        deprecated = {"无歌词", "俄语/法语", "俄语/德语", "法语/俄语", "法语/英语"}
        self.assertFalse(deprecated & {item.get("language", "") for item in self.catalog})
        multilingual = [
            (item.get("composer"), item.get("title"), item.get("language"))
            for item in self.catalog
            if "/" in item.get("language", "")
        ]
        self.assertEqual(
            multilingual,
            [("Reynaldo Hahn/哈恩", "La pastorale de Noël", "法语/拉丁语")],
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.app_js = (ROOT / "js" / "app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "css" / "style.css").read_text(encoding="utf-8")
        cls.site_config = (ROOT / "site-config.json").read_text(encoding="utf-8")

    def test_pdf_preview_is_explicit_and_starts_blank(self):
        self.assertIn('id="mPreview" src="about:blank"', self.index_html)
        self.assertIn('id="btnLoadPreview"', self.index_html)
        self.assertIn("preview.contentWindow.location.replace(currentPdfUrl)", self.app_js)
        self.assertIn("delete preview.dataset.loadedUrl", self.app_js)

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
        self.assertIn('"keyStrategy": "catalog_filename"', self.site_config)


if __name__ == "__main__":
    unittest.main()

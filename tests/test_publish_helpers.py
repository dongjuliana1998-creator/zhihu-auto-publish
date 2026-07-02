import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import daily_publish_v2 as daily
import zhihu_publish_common as common
from zhihu_publish_common import is_published, load_config, resolve_answer_url, validate_content


class FakePage:
    def __init__(self, url, links=None):
        self.url = url
        self.links = links or []

    def evaluate(self, _script):
        return self.links


def test_find_images_for_article_matches_stem(tmp_path, monkeypatch):
    images = tmp_path / "images"
    images.mkdir()
    (images / "article_1_img1.png").write_bytes(b"x")
    (images / "article_10_img1.png").write_bytes(b"x")
    article = tmp_path / "article_1.txt"
    article.write_text("title\n\nbody", encoding="utf-8")

    monkeypatch.setattr(daily, "IMAGES_DIR", images)

    found = daily.find_images_for_article(article)

    assert [Path(p).name for p in found] == ["article_1_img1.png"]


def test_is_published_checks_articles_and_answers():
    log = {
        "articles": {"article_1.txt": {"url": "https://zhuanlan.zhihu.com/p/1"}},
        "answers": {"answer_1.txt": {"url": "https://www.zhihu.com/question/1/answer/2"}},
    }

    assert is_published(log, "article_1.txt")
    assert is_published(log, "answer_1.txt")
    assert not is_published(log, "article_2.txt")


def test_validate_content_warns_for_answer_placeholder_and_length():
    warnings = validate_content("【配图 1：示例】", "answers")

    assert any("shorter" in warning for warning in warnings)
    assert any("image placeholder" in warning for warning in warnings)


def test_validate_content_accepts_answer_boundaries():
    assert not validate_content("x" * 300, "answers")
    assert not validate_content("x" * 800, "answers")
    assert any("longer" in warning for warning in validate_content("x" * 801, "answers"))


def test_resolve_answer_url_from_current_url():
    page = FakePage("https://www.zhihu.com/question/123/answer/456")

    assert resolve_answer_url(page, "https://www.zhihu.com/question/123", wait_sec=0.01) == (
        "https://www.zhihu.com/question/123/answer/456"
    )


def test_resolve_answer_url_from_dom_link():
    page = FakePage(
        "https://www.zhihu.com/question/123/write",
        ["https://www.zhihu.com/question/123/answer/456?utm=test"],
    )

    assert resolve_answer_url(page, "https://www.zhihu.com/question/123", wait_sec=0.01) == (
        "https://www.zhihu.com/question/123/answer/456"
    )


def test_load_config_reads_config_file(tmp_path, monkeypatch):
    cfg = tmp_path / "zhihu_config.json"
    cfg.write_text('{"zhihu": {"editor_wait_timeout_sec": 12}}', encoding="utf-8")
    monkeypatch.setattr(common, "ZH_CONFIG_FILE", cfg)

    assert load_config()["zhihu"]["editor_wait_timeout_sec"] == 12

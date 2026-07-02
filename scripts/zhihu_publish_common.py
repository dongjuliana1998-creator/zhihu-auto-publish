#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Common helpers for Zhihu publishing scripts."""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
CONFIG_DIR = PROJECT_ROOT / "config"
ARTICLES_DIR = PROJECT_ROOT / "articles"
ANSWERS_DIR = PROJECT_ROOT / "answers"
IMAGES_DIR = PROJECT_ROOT / "images"
DEBUG_DIR = PROJECT_ROOT / "debug"
LOG_FILE = PROJECT_ROOT / "publish_log.json"
ZH_CONFIG_FILE = CONFIG_DIR / "zhihu_config.json"
CONTENT_CONFIG_FILE = CONFIG_DIR / "content_config.json"


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_config() -> dict:
    return load_json(ZH_CONFIG_FILE, {}) or {}


def load_content_config() -> dict:
    return load_json(CONTENT_CONFIG_FILE, {}) or {}


def cookie_file() -> Path:
    cfg = load_config()
    configured = cfg.get("zhihu", {}).get("cookie_file", "zhihu_cookies.json")
    path = Path(configured)
    if path.is_absolute():
        return path
    return CONFIG_DIR / path


def load_cookies(context) -> bool:
    path = cookie_file()
    if not path.exists():
        logging.error("Cookie file missing: %s. Please run: python scripts/zhihu_auth.py", path)
        return False
    cookies = load_json(path, [])
    if not cookies:
        logging.error("Cookie file is empty: %s. Please run: python scripts/zhihu_auth.py", path)
        return False
    context.add_cookies(cookies)
    logging.info("Loaded %s cookies from %s", len(cookies), path)
    return True


def refresh_cookies(headless: bool = False) -> bool:
    """Run the QR-code login flow and save a fresh cookie file."""
    try:
        from zhihu_auth import ZhihuAuth
    except Exception:
        logging.exception("Failed to import zhihu_auth for cookie refresh")
        return False
    try:
        logging.info("Refreshing Zhihu cookies via QR login flow")
        return bool(ZhihuAuth(headless=headless).login())
    except Exception:
        logging.exception("Cookie refresh failed")
        return False


def load_cookies_with_refresh(context, *, refresh_on_missing: bool = True) -> bool:
    if load_cookies(context):
        return True
    if not refresh_on_missing:
        return False
    if not refresh_cookies(headless=False):
        return False
    return load_cookies(context)


def ensure_logged_in(page, context) -> bool:
    """Refresh cookies once when Zhihu redirects to login/signin."""
    if "signin" not in page.url and "login" not in page.url:
        return True
    logging.warning("Zhihu session expired at %s; starting cookie refresh", page.url)
    if not refresh_cookies(headless=False):
        return False
    try:
        context.clear_cookies()
    except Exception:
        logging.debug("clear_cookies failed before cookie reload", exc_info=True)
    return load_cookies(context)


def init_browser(pw):
    return pw.chromium.launch(
        headless=False,
        slow_mo=50,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--no-first-run",
        ],
    )


def init_context(browser):
    return browser.new_context(
        viewport={"width": 1440, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )


@contextmanager
def browser_session():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = init_browser(pw)
        context = init_context(browser)
        try:
            if not load_cookies_with_refresh(context):
                raise RuntimeError("Cookie missing or expired; refresh failed")
            yield context
        finally:
            browser.close()


def empty_log() -> dict:
    return {"articles": {}, "answers": {}, "last_run": None}


def load_log() -> dict:
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logging.warning("publish_log.json is invalid: %s; backing up and resetting", exc)
            try:
                LOG_FILE.rename(LOG_FILE.with_suffix(".json.bak"))
            except OSError:
                logging.exception("Failed to back up invalid publish log")
    return empty_log()


def save_log(log: dict) -> None:
    LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_published(log: dict, file_key: str) -> bool:
    return file_key in log.get("articles", {}) or file_key in log.get("answers", {})


def mark_published(log: dict, file_key: str, url: str, title: str, content_type: str) -> None:
    if file_key.startswith("tmp_"):
        return
    log.setdefault(content_type, {})[file_key] = {
        "url": url,
        "title": title,
        "published_at": now_str(),
        "content_type": content_type,
    }
    log["last_run"] = now_str()
    save_log(log)


def setup_logging(prefix: str = "publish") -> Path:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DEBUG_DIR / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    logging.info("Debug log: %s", log_path)
    return log_path


def config_int(*keys: str, default: int) -> int:
    node: Any = load_config()
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    try:
        return int(node)
    except (TypeError, ValueError):
        return default


def wait_for_editor(page, timeout_sec: int | None = None, prefer_body: bool = False):
    timeout = timeout_sec or config_int("zhihu", "editor_wait_timeout_sec", default=45)
    deadline = time.time() + timeout
    delay = 1
    last_best_h = 0
    while time.time() < deadline:
        try:
            editors = page.locator(".public-DraftEditor-content")
            count = editors.count()
            best = None
            best_h = 0
            for i in range(count):
                ed = editors.nth(i)
                try:
                    if not ed.is_visible(timeout=500):
                        continue
                    box = ed.bounding_box()
                    if box is None:
                        time.sleep(0.5)
                        box = ed.bounding_box()
                    h = box["height"] if box else 0
                    if prefer_body and count >= 2 and i == 1:
                        best, best_h = ed, h
                        break
                    if h > best_h:
                        best, best_h = ed, h
                except Exception:
                    logging.debug("Editor candidate check failed", exc_info=True)
            last_best_h = best_h
            if best and best_h > 20:
                best.click()
                return best
            logging.debug("Waiting for editor: count=%s best_h=%s", count, best_h)
        except Exception:
            logging.debug("Editor lookup failed", exc_info=True)
        time.sleep(min(delay, max(1, deadline - time.time())))
        delay = min(delay * 2, 8)
    raise TimeoutError(f"Editor not ready (best_h={last_best_h:.0f}, timeout={timeout}s)")


def extract_answer_url_from_dom(page, question_url: str) -> str | None:
    qid_match = re.search(r"/question/(\d+)", question_url)
    qid = qid_match.group(1) if qid_match else None
    links = page.evaluate(
        """() => {
            const urls = [];
            const answerItems = document.querySelectorAll('.AnswerItem, [data-zop*="answer"]');
            for (const item of answerItems) {
                const id = item.getAttribute('name') || item.getAttribute('data-za-extra-module');
                if (id && /\\d{5,}/.test(id)) urls.push(location.origin + location.pathname.replace(/\\/write\\/?$/, '') + '/answer/' + id.match(/\\d{5,}/)[0]);
            }
            for (const a of document.querySelectorAll('a[href*="/answer/"]')) {
                urls.push(a.href || a.getAttribute('href') || '');
            }
            return urls.filter(Boolean);
        }"""
    )
    for link in links:
        if "/answer/" not in link or "/write" in link:
            continue
        if qid and f"/question/{qid}/" not in link:
            continue
        return link.split("?")[0]
    return None


def resolve_answer_url(page, question_url: str, wait_sec: int = 45) -> str | None:
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        cur_url = page.url
        if "/answer/" in cur_url and "/write" not in cur_url:
            return re.sub(r"/edit/?$", "", cur_url).split("?")[0]
        dom_url = extract_answer_url_from_dom(page, question_url)
        if dom_url:
            return dom_url
        time.sleep(2)
    return None


def content_limits(content_type: str) -> tuple[int, int]:
    # content_config.json is the authority for publishing rules. zhihu_config.json
    # keeps duplicate values only for human-readable site configuration.
    cfg = load_content_config()
    spec = cfg.get("answer_spec" if content_type == "answers" else "article_spec", {})
    return int(spec.get("min_chars", 0)), int(spec.get("max_chars", 10**9))


def forbidden_patterns() -> list[str]:
    spec = load_content_config().get("answer_spec", {})
    patterns = spec.get("_anti_ai_forbidden_patterns", [])
    return [str(p).strip("'\"") for p in patterns]


def validate_content(content: str, content_type: str) -> list[str]:
    warnings = []
    min_chars, max_chars = content_limits(content_type)
    length = len(content)
    if min_chars and length < min_chars:
        warnings.append(f"{content_type} content is shorter than {min_chars} chars: {length}")
    if max_chars and length > max_chars:
        warnings.append(f"{content_type} content is longer than {max_chars} chars: {length}")
    if content_type == "answers" and re.search(r"【\s*配图\s*\d+", content):
        warnings.append("answer contains image placeholder; answers should be plain text")
    for pattern in forbidden_patterns():
        plain = re.sub(r"[.'/（）()]+", "", pattern)
        if plain and plain in content:
            warnings.append(f"content contains anti-AI forbidden pattern: {pattern}")
    return warnings


def confirm_or_continue(warnings: list[str], assume_yes: bool = False) -> bool:
    if not warnings:
        return True
    for warning in warnings:
        logging.warning("[CONTENT CHECK] %s", warning)
    if assume_yes:
        return True
    try:
        answer = input("Continue publishing despite warnings? [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}

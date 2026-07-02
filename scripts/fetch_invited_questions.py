#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_invited_questions.py - 抓取知乎「邀请回答」通知并入库。

默认使用标准库 HTTP 客户端直接带 Cookie 调知乎 API，避免每次启动浏览器。
如知乎临时要求浏览器上下文，可用 --use-browser 走 Playwright fetch 兜底。
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
COOKIE = ROOT / "zhihu_cookies.json"
INVITED = ROOT / "invited_questions.json"
QUESTION_BANK = ROOT / "question_bank.json"

DEFAULT_MAX_PAGES = 10
PAGE_LIMIT = 20
DAILY_LIMIT = 3

API_BASE = "https://www.zhihu.com/api/v4/notifications/v2/recent"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class InviteApiError(RuntimeError):
    pass


class InviteAuthError(InviteApiError):
    pass


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        backup = path.with_suffix(path.suffix + ".bak")
        path.replace(backup)
        print(f"  [WARN] {path.name} 损坏: {exc}; 已备份为 {backup.name}")
        return default


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cookies() -> list[dict]:
    cookies = load_json(COOKIE, [])
    if not isinstance(cookies, list) or not cookies:
        raise InviteAuthError(f"Cookie 不存在或为空: {COOKIE}。请先运行 zhihu_auth.py 重新登录。")
    return cookies


def cookie_header(cookies: list[dict]) -> str:
    pairs = []
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        domain = cookie.get("domain", "")
        if not name or value is None:
            continue
        if "zhihu.com" not in domain and domain:
            continue
        pairs.append(f"{name}={value}")
    if not pairs:
        raise InviteAuthError("Cookie 文件里没有可用于 zhihu.com 的 Cookie。")
    return "; ".join(pairs)


def build_api_url(offset: str | None = None) -> str:
    params = {"entry_name": "invite", "limit": str(PAGE_LIMIT)}
    if offset:
        params["offset"] = str(offset)
    return f"{API_BASE}?{urllib.parse.urlencode(params)}"


def parse_next_offset(paging: dict, current_offset: str | None = None) -> str | None:
    if not paging or paging.get("is_end") is True:
        return None
    next_url = paging.get("next") or ""
    if not next_url:
        return None
    parsed = urllib.parse.urlparse(next_url)
    params = urllib.parse.parse_qs(parsed.query)
    values = params.get("offset") or []
    next_offset = values[0] if values else None
    if not next_offset or next_offset == current_offset:
        return None
    return next_offset


def request_invite_api_direct(cookies: list[dict], offset: str | None = None, timeout: int = 20) -> dict:
    url = build_api_url(offset)
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie_header(cookies),
        "Referer": "https://www.zhihu.com/notifications",
        "User-Agent": USER_AGENT,
        "X-Requested-With": "fetch",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise InviteAuthError(f"知乎 API 返回 {exc.code}，Cookie 可能已失效。") from exc
        raise InviteApiError(f"知乎 API HTTP 错误: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise InviteApiError(f"知乎 API 网络错误: {exc.reason}") from exc

    if status >= 400:
        raise InviteApiError(f"知乎 API HTTP 错误: {status}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InviteApiError(f"知乎 API 返回非 JSON 内容: {raw[:200]}") from exc


def request_invite_api_browser(page, offset: str | None = None) -> dict:
    url = build_api_url(offset)
    result = page.evaluate(
        """async (url) => {
            const resp = await fetch(url, {
                headers: {
                    "x-requested-with": "fetch",
                    "accept": "application/json, text/plain, */*",
                },
                credentials: "include",
            });
            const text = await resp.text();
            return {status: resp.status, ok: resp.ok, text};
        }""",
        url,
    )
    status = result.get("status", 0)
    if status in (401, 403):
        raise InviteAuthError(f"知乎 API 返回 {status}，Cookie 可能已失效。")
    if not result.get("ok"):
        raise InviteApiError(f"知乎 API HTTP 错误: {status}; {result.get('text', '')[:200]}")
    try:
        return json.loads(result.get("text") or "{}")
    except json.JSONDecodeError as exc:
        raise InviteApiError(f"知乎 API 返回非 JSON 内容: {(result.get('text') or '')[:200]}") from exc


def call_invite_api(
    *,
    cookies: list[dict] | None = None,
    page=None,
    offset: str | None = None,
    retry: int = 2,
    timeout: int = 20,
) -> tuple[list[dict], str | None]:
    last_error: Exception | None = None
    for attempt in range(retry + 1):
        try:
            if page is not None:
                data = request_invite_api_browser(page, offset)
            else:
                if cookies is None:
                    raise ValueError("cookies is required when page is not provided")
                data = request_invite_api_direct(cookies, offset, timeout=timeout)
            notifications = data.get("data", [])
            if not isinstance(notifications, list):
                raise InviteApiError("知乎 API data 字段不是列表")
            next_offset = parse_next_offset(data.get("paging", {}), current_offset=offset)
            return notifications, next_offset
        except InviteAuthError:
            raise
        except Exception as exc:
            last_error = exc
            print(f"  [WARN] API 调用失败 ({attempt + 1}/{retry + 1}): {exc}")
            if attempt < retry:
                time.sleep(2 * (attempt + 1))
    raise InviteApiError(str(last_error) if last_error else "未知 API 错误")


def first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def extract_qid_from_url(url: str) -> str:
    match = re.search(r"/(?:question|questions)/(\d+)", url or "")
    return match.group(1) if match else ""


def normalize_timestamp(value: Any) -> int:
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return int(time.time())
    if ts > 10_000_000_000:
        ts //= 1000
    return max(0, ts)


def parse_notification(notif: dict) -> dict | None:
    """解析单条通知，尽量兼容知乎通知 API 的不同字段形态。"""
    try:
        content = notif.get("content") or {}
        target = notif.get("target") or {}
        content_target = content.get("target") or {}

        target_url = first_non_empty(content_target.get("link"), target.get("url"))
        qid = first_non_empty(target.get("id"), extract_qid_from_url(target_url))
        if not qid:
            print(f"  [WARN] 跳过无 question id 的通知: {notif.get('id', '')}")
            return None

        title = first_non_empty(content_target.get("text"), target.get("title"), content_target.get("title"))
        url = first_non_empty(content_target.get("link"), f"https://www.zhihu.com/question/{qid}")
        url = url.replace("http://", "https://").split("?")[0].split("#")[0]
        if "/api/v4/questions/" in url:
            url = f"https://www.zhihu.com/question/{qid}"

        actors = content.get("actors") or notif.get("actors") or []
        actor = actors[0] if actors else (notif.get("actor") or {})
        inviter_name = first_non_empty(actor.get("name"), "未知")
        inviter_url = first_non_empty(actor.get("link"))
        if not inviter_url and actor.get("url_token"):
            inviter_url = f"https://www.zhihu.com/people/{actor['url_token']}"

        created_time = normalize_timestamp(
            notif.get("create_time") or notif.get("created_time") or notif.get("created")
        )
        return {
            "qid": str(qid),
            "title": title,
            "url": url,
            "inviter": inviter_name,
            "inviter_url": inviter_url,
            "invited_at": datetime.fromtimestamp(created_time).strftime("%Y-%m-%d %H:%M"),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "notification_id": str(notif.get("id", "")),
        }
    except Exception as exc:
        print(f"  [WARN] 解析通知失败: {exc}")
        return None


def fetch_all_invites(
    *,
    cookies: list[dict] | None = None,
    page=None,
    max_pages: int = DEFAULT_MAX_PAGES,
    timeout: int = 20,
) -> list[dict]:
    all_notifs: list[dict] = []
    offset = None
    seen_offsets: set[str] = set()
    seen_notification_ids: set[str] = set()

    for page_num in range(max_pages):
        print(f"  获取第 {page_num + 1} 页...")
        notifications, next_offset = call_invite_api(
            cookies=cookies,
            page=page,
            offset=offset,
            timeout=timeout,
        )
        if not notifications:
            print("  没有更多数据")
            break

        added = 0
        for notif in notifications:
            notif_id = str(notif.get("id") or "")
            if notif_id and notif_id in seen_notification_ids:
                continue
            if notif_id:
                seen_notification_ids.add(notif_id)
            all_notifs.append(notif)
            added += 1
        print(f"    本页 {len(notifications)} 条，新数据 {added} 条，累计 {len(all_notifs)} 条")

        if not next_offset:
            break
        if next_offset in seen_offsets:
            print(f"  [WARN] API 返回重复 offset={next_offset}，停止分页避免循环")
            break
        seen_offsets.add(next_offset)
        offset = next_offset
        time.sleep(0.5)

    return all_notifs


def normalize_invited_format(invited_data: dict) -> dict:
    invited_data.setdefault("questions", [])
    for q in invited_data.get("questions", []):
        if "question_id" in q and "qid" not in q:
            q["qid"] = q["question_id"]
        if "question_title" in q and "title" not in q:
            q["title"] = q["question_title"]
        q.setdefault("qid", "")
        q.setdefault("title", "")
        q.setdefault("url", f"https://www.zhihu.com/question/{q['qid']}" if q.get("qid") else "")
        q.setdefault("inviter", "")
        q.setdefault("inviter_url", "")
        q.setdefault("status", "pending")
        q.setdefault("used_at", None)
        q.setdefault("overflow_to_bank", False)
    return invited_data


def merge_into_invited_json(new_invites: list[dict], dry_run: bool = False) -> tuple[dict, int]:
    invited_data = normalize_invited_format(load_json(INVITED, {"questions": []}))
    existing_qids = {str(q.get("qid") or q.get("question_id")) for q in invited_data["questions"] if q.get("qid") or q.get("question_id")}
    added = 0

    for inv in new_invites:
        qid = str(inv.get("qid") or "")
        if not qid or qid in existing_qids:
            continue
        invited_data["questions"].append(
            {
                "qid": qid,
                "title": inv.get("title", ""),
                "url": inv.get("url", f"https://www.zhihu.com/question/{qid}"),
                "inviter": inv.get("inviter", ""),
                "inviter_url": inv.get("inviter_url", ""),
                "invited_at": inv.get("invited_at", ""),
                "fetched_at": inv.get("fetched_at", ""),
                "status": "pending",
                "used_at": None,
                "overflow_to_bank": False,
                "notification_id": inv.get("notification_id", ""),
            }
        )
        existing_qids.add(qid)
        added += 1

    total_pending = sum(1 for q in invited_data["questions"] if q.get("status") == "pending")
    print(
        f"\n合并结果: 新增 {added} 条，invited_questions.json "
        f"共有 {len(invited_data['questions'])} 条（{total_pending} 条 pending）"
    )

    if not dry_run:
        save_json(INVITED, invited_data)
        print(f"  [OK] 已写入 {INVITED}")

    return invited_data, total_pending


def overflow_to_question_bank(invited_data: dict, dry_run: bool = False) -> int:
    invited_data = normalize_invited_format(invited_data)
    pending = [q for q in invited_data["questions"] if q.get("status") == "pending"]
    pending.sort(key=lambda x: x.get("invited_at") or "2000-01-01")

    if len(pending) <= DAILY_LIMIT:
        print(f"\npending 邀请 {len(pending)} 条 <= 限额 {DAILY_LIMIT}，无需溢出")
        return 0

    overflow_items = pending[:-DAILY_LIMIT]
    print(f"\npending 邀请 {len(pending)} 条 > 限额 {DAILY_LIMIT}，溢出 {len(overflow_items)} 条到 question_bank")

    bank = load_json(QUESTION_BANK, {"questions": []})
    bank.setdefault("questions", [])
    bank_qids = {str(q.get("qid") or q.get("question_id")) for q in bank["questions"] if q.get("qid") or q.get("question_id")}
    added_to_bank = 0

    for item in overflow_items:
        qid = str(item.get("qid") or "")
        if not qid:
            continue
        item["overflow_to_bank"] = True
        item["overflowed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        item["status"] = "overflowed"

        if qid in bank_qids:
            continue
        bank["questions"].append(
            {
                "qid": qid,
                "title": item.get("title", ""),
                "url": item.get("url", f"https://www.zhihu.com/question/{qid}"),
                "pillar": "cross_border_tools",
                "source": "invited_overflow",
                "inviter": item.get("inviter", ""),
                "added_at": datetime.now().strftime("%Y-%m-%d"),
                "used": False,
            }
        )
        bank_qids.add(qid)
        added_to_bank += 1

    print(f"  溢出到 question_bank: {added_to_bank} 条新问题")

    if not dry_run:
        save_json(INVITED, invited_data)
        save_json(QUESTION_BANK, bank)
        print(f"  [OK] 已更新 {INVITED}")
        print(f"  [OK] 已写入 {QUESTION_BANK}")
    return added_to_bank


def fetch_with_browser(cookies: list[dict], max_pages: int, timeout: int) -> list[dict]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=USER_AGENT,
            locale="zh-CN",
        )
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto("https://www.zhihu.com", wait_until="domcontentloaded", timeout=timeout * 1000)
        time.sleep(1)
        try:
            return fetch_all_invites(page=page, max_pages=max_pages, timeout=timeout)
        finally:
            browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="试运行，不写入文件")
    parser.add_argument("--use-browser", action="store_true", help="使用 Playwright 浏览器 fetch 兜底")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--timeout", type=int, default=20, help="HTTP 超时秒数")
    args = parser.parse_args()

    print("=" * 60)
    print("fetch_invited_questions.py - 知乎邀请回答 API 抓取")
    print("=" * 60)

    try:
        print("\n[1/4] 加载 Cookie...")
        cookies = load_cookies()
        print(f"  [OK] {len(cookies)} 条 Cookie")

        print("\n[2/4] 调用邀请回答 API...")
        if args.use_browser:
            raw_notifs = fetch_with_browser(cookies, args.max_pages, args.timeout)
        else:
            raw_notifs = fetch_all_invites(cookies=cookies, max_pages=args.max_pages, timeout=args.timeout)

        print(f"\n[3/4] 解析 {len(raw_notifs)} 条通知...")
        new_invites = []
        for notif in raw_notifs:
            parsed = parse_notification(notif)
            if parsed and parsed["qid"]:
                new_invites.append(parsed)
        print(f"  成功解析 {len(new_invites)} 条邀请")

        if not new_invites:
            print("  [WARN] 没有抓到任何邀请，请检查 Cookie 或 API 返回结构")
            return 1

        print(f'\n[4/4] 合并到 invited_questions.json{" (dry-run)" if args.dry_run else ""}...')
        invited_data, _total_pending = merge_into_invited_json(new_invites, dry_run=args.dry_run)
        overflow_to_question_bank(invited_data, dry_run=args.dry_run)
    except InviteAuthError as exc:
        print(f"\n[ERROR] {exc}")
        return 2
    except InviteApiError as exc:
        print(f"\n[ERROR] {exc}")
        print("        如直接 HTTP 调用持续失败，可尝试加 --use-browser 使用 Playwright fetch。")
        return 3

    print("\n" + "=" * 60)
    print("[OK] 完成")
    if args.dry_run:
        print("(dry-run 模式，未写入文件)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish_answer_v11.py - 知乎回答发布（支持配图上传）
重写版 - 2026-07-01
"""

import sys, os, json, time, random, re, argparse
import logging
from contextlib import nullcontext
from pathlib import Path
from zhihu_publish_common import (
    ensure_logged_in,
    IMAGES_DIR,
    LOG_FILE,
    PROJECT_ROOT,
    confirm_or_continue,
    cookie_file,
    load_cookies_with_refresh,
    resolve_answer_url,
    setup_logging,
    validate_content,
    wait_for_editor,
)

ROOT = PROJECT_ROOT
COOKIE_FILE = cookie_file()

BASE_URL = "https://www.zhihu.com"


class NoopBrowser:
    def close(self):
        pass

def load_log():
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception) as e:
            print(f"[WARN] publish_log.json 损坏 ({e})，备份后重置")
            try:
                bak = LOG_FILE.with_suffix(".json.bak")
                LOG_FILE.rename(bak)
                print(f"       已备份到 {bak.name}")
            except:
                pass
    return {"articles": {}, "answers": {}, "last_run": None}

def save_log(log):
    LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

def mark_published(log, fname, url, filekey):
    """标记文件为已发布，避免重复"""
    if filekey.startswith("tmp_"):
        return
    stem = Path(fname).stem
    log["answers"][stem] = {
        "url": url,
        "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "date": time.strftime("%Y-%m-%d")
    }
    save_log(log)

def is_published(log, fname):
    stem = Path(fname).stem
    if stem in log.get("answers", {}):
        entry = log["answers"][stem]
        if entry.get("date") == time.strftime("%Y-%m-%d"):
            return True
    return False

def parse_content_with_images(content, image_path=None):
    """解析内容，分离文本段和图片占位符"""
    import re
    segments = []
    pattern = r'【配图\s*(\d+)[:：]\s*(.+?)】'
    
    last_end = 0
    for m in re.finditer(pattern, content):
        if m.start() > last_end:
            text = content[last_end:m.start()]
            if text.strip():
                segments.append({"type": "text", "content": text})
        segments.append({"type": "image", "num": int(m.group(1)), "desc": m.group(2).strip()})
        last_end = m.end()
    
    if last_end < len(content):
        text = content[last_end:]
        if text.strip():
            segments.append({"type": "text", "content": text})
    
    # 如果没有任何配图占位符，但有图片文件，在末尾加一个图片段
    has_image_segment = any(s["type"] == "image" for s in segments)
    if not has_image_segment and image_path:
        segments.append({"type": "image", "num": 1, "desc": "配图"})
    
    return segments

def upload_image_to_editor(page, image_path):
    """上传图片到编辑器"""
    abs_path = str(Path(image_path).resolve())
    print(f"      上传: {abs_path}")
    
    try:
        img_btn = page.locator("button[aria-label='图片']").first
        if img_btn.count() > 0 and img_btn.is_visible(timeout=3000):
            img_btn.click()
            time.sleep(1)
    except:
        print("      [WARN] 未找到图片按钮，尝试直接上传")
    
    try:
        file_input = page.locator("input[type='file'][accept*='image']").first
        file_input.set_input_files(abs_path)
        print("      [OK] 文件已选择")
    except Exception as e:
        print(f"      [FAIL] set_input_files: {e}")
        return False
    
    # 等待图片出现在编辑器中
    max_wait = 15
    image_detected = False
    for i in range(max_wait):
        time.sleep(1)
        try:
            imgs = page.locator(".public-DraftEditor-content img")
            if imgs.count() > 0:
                image_detected = True
                print(f"      [OK] 图片已出现 (等{i+1}s)")
                break
        except:
            pass
        if i % 5 == 4:
            print(f"      等待图片... ({i+1}s)")
    else:
        print("      [WARN] 图片未在编辑器中检测到，继续...")
    
    # 关闭上传面板
    time.sleep(0.5)
    closed = False
    for sel in ['.Modal-closeButton', 'button[aria-label="关闭"]', '[class*="close"]']:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible(timeout=500):
                btn.click()
                time.sleep(0.5)
                closed = True
                break
        except:
            pass
    if not closed:
        try:
            page.keyboard.press("Escape")
            time.sleep(0.5)
        except:
            pass
    
    return image_detected


def upload_image_with_retry(page, image_path, attempts=3):
    for attempt in range(1, attempts + 1):
        logging.info("Uploading answer image attempt %s/%s: %s", attempt, attempts, image_path)
        if upload_image_to_editor(page, image_path):
            return True
        if attempt < attempts:
            time.sleep(2 * attempt)
    return False

def type_text(page, text):
    """逐字输入文本到 Draft.js 编辑器"""
    chunk_size = random.randint(3, 8)
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i+chunk_size]
        page.keyboard.type(chunk, delay=random.randint(10, 30))
        if random.random() < 0.15:
            time.sleep(random.uniform(0.1, 0.3))

def publish_answer(question_url, content, image_path=None, dry_run=False, shared_context=None):
    """发布一条回答"""
    from playwright.sync_api import sync_playwright
    
    result = {"success": False, "error": None, "url": None}
    log = load_log()
    
    print(f"\n{'='*60}")
    print(f"  发布回答: {question_url}")
    print(f"  内容长度: {len(content)} 字")
    print(f"  配图: {image_path or '无'}")
    if dry_run:
        print(f"  [DRY-RUN] 仅模拟，不实际发布")
    print(f"{'='*60}")

    warnings = validate_content(content, "answers")
    if not confirm_or_continue(warnings, assume_yes=dry_run):
        return {"success": False, "url": None, "error": "Stopped by content validation warnings"}
    
    if dry_run:
        print(f"\n[DRY-RUN] 模拟完成")
        return {"success": True, "url": "dry-run"}
    
    segments = parse_content_with_images(content, image_path)
    if image_path and not any(s["type"] == "image" for s in segments):
        segments.append({"type": "image", "num": 1, "desc": "配图"})
    
    with (nullcontext() if shared_context else sync_playwright()) as p:
        browser = None
        try:
            if shared_context:
                browser = NoopBrowser()
                ctx = shared_context
            else:
                print("[启动浏览器]")
                browser = p.chromium.launch(
                    headless=False,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ]
                )

                ctx = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                # 加载 Cookie
                try:
                    if not load_cookies_with_refresh(ctx):
                        result["error"] = f"Cookie refresh/load failed: {COOKIE_FILE}"
                        browser.close()
                        return result
                    print("[OK] Cookie 已加载")
                except Exception as e:
                    result["error"] = f"Cookie 加载异常: {e}"
                    browser.close()
                    return result
            
            page = ctx.new_page()
            
            # Step 1: 打开问题页
            print("[1/6] 打开问题页...")
            page.goto(question_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(4, 6))
            
            if "signin" in page.url or "login" in page.url:
                if ensure_logged_in(page, ctx):
                    page.goto(question_url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(random.uniform(4, 6))
                else:
                    result["error"] = "Cookie refresh failed"
                    browser.close()
                    return result
            if "signin" in page.url or "login" in page.url:
                result["error"] = "Cookie 过期"
                browser.close()
                return result
            
            if page.url.endswith("/403"):
                result["error"] = "反爬(403)"
                browser.close()
                return result
            
            # Step 2: 直接导航到写回答页
            print("[2/6] 导航到写回答页...")
            qid = question_url.split("/question/")[-1].split("?")[0].split("/")[0]
            page.goto(f"{BASE_URL}/question/{qid}/write", wait_until="domcontentloaded", timeout=20000)
            time.sleep(3)
            
            # Step 3: 等待编辑器
            print("[3/6] 等待编辑器...")
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(3)
            try:
                editor = wait_for_editor(page)
                best_h = 999
            except TimeoutError:
                editor = None
                best_h = 0
            for attempt in range(0 if editor else 15):
                time.sleep(1)
                editors = page.locator(".public-DraftEditor-content")
                count = editors.count()
                if count == 0:
                    if attempt % 3 == 0:
                        print(f"    (attempt {attempt+1}: 0 editors)")
                    continue
                
                best_ed = None
                best_h = 0
                for i in range(count):
                    ed = editors.nth(i)
                    try:
                        if ed.is_visible(timeout=300):
                            box = ed.bounding_box()
                            h = box["height"] if box else 0
                            if box and h > best_h:
                                best_ed = ed
                                best_h = h
                    except:
                        pass
                
                if best_ed and best_h > 20:
                    editor = best_ed
                    editor.click()
                    time.sleep(1)
                    print(f"  [OK] 编辑器就绪 height={best_h:.0f}px (attempt {attempt+1})")
                    break
                
                if attempt % 3 == 0:
                    print(f"    (attempt {attempt+1}: {count} editors, best_h={best_h:.0f})")
            
            if not editor:
                result["error"] = f"编辑器未就绪 (best_h={best_h:.0f})"
                browser.close()
                return result
            
            # Step 4: 输入内容
            print("[4/6] 输入内容...")
            img_counter = 0
            for seg_idx, seg in enumerate(segments):
                if seg["type"] == "text":
                    print(f"  [文本] {len(seg['content'])}字...")
                    type_text(page, seg["content"])
                    time.sleep(random.uniform(0.5, 1.0))
                elif seg["type"] == "image":
                    if not image_path:
                        print(f"  [图片] 无图片文件，跳过")
                        continue
                    img_counter += 1
                    print(f"  [图片#{img_counter}] {seg.get('desc', '')}")
                    ok = upload_image_with_retry(page, image_path)
                    if ok:
                        print(f"  ✓ 配图#{img_counter} 插入成功")
                    else:
                        result["error"] = f"Image upload failed after retries: {image_path}"
                        browser.close()
                        return result
                        print(f"  ✗ 配图#{img_counter} 失败")
                    time.sleep(1)
            
            # 输入完成后停顿
            pause = random.uniform(3, 6)
            print(f"  等待 {pause:.0f}s...")
            time.sleep(pause)
            
            # Step 5: 点击发布
            print("[5/6] 点击发布...")
            pub_clicked = False
            
            # 方法1: 通过 JS 查找并点击
            js_pub = """() => {
const strip = (s) => (s||'').replace(/[\\u200b\\u200c\\u200d\\uFEFF]/g, '').trim();
const btns = document.querySelectorAll('button');
const targets = ['发布回答', '发布', '提交修改', '提交'];
for (let ti = 0; ti < targets.length; ti++) {
    const target = targets[ti];
    for (let bi = 0; bi < btns.length; bi++) {
        const b = btns[bi];
        const t = strip(b.textContent);
        if (t === target) { b.scrollIntoView({block:'center'}); b.click(); return 'clicked:'+t; }
    }
}
return 'not-found';
}"""
            r = page.evaluate(js_pub)
            print(f"  JS click: {r}")
            if r and r.startswith("clicked:"):
                pub_clicked = True
            
            # 方法2: 用 Playwright locator 回退
            if not pub_clicked:
                for sel in [
                    "button:has-text('发布回答')",
                    "button:has-text('发布')",
                    "button[class*='primary']:has-text('发布')",
                ]:
                    try:
                        btn = page.locator(sel).first
                        if btn.count() > 0 and btn.is_visible(timeout=2000):
                            btn.scroll_into_view_if_needed()
                            time.sleep(0.5)
                            btn.click(force=True, timeout=5000)
                            pub_clicked = True
                            print(f"  Locator click: {sel}")
                            break
                    except:
                        continue
            
            if not pub_clicked:
                result["error"] = "无法点击发布按钮"
                browser.close()
                return result
            
            # Step 6: 等待发布完成并获取 URL
            print("[6/6] 等待发布...")
            # 等待 URL 变化——发布成功后通常会跳转到答案页
            resolved_url = resolve_answer_url(page, question_url, wait_sec=45)
            for i in range(20):
                time.sleep(1)
                cur_url = page.url
                if "/answer/" in cur_url and "/write" not in cur_url:
                    break
                if i == 5:
                    print(f"  当前 URL: {cur_url}")
            
            cur_url = resolved_url or page.url
            
            if "/edit" in cur_url:
                clean = re.sub(r'/edit/?$', '', cur_url)
                result["success"] = True
                result["url"] = clean
                print(f"  [SUCCESS] (编辑页) → {clean}")
            elif "/answer/" in cur_url:
                result["success"] = True
                result["url"] = cur_url
                print(f"  [SUCCESS] → {cur_url}")
            else:
                try:
                    form = page.locator(".public-DraftEditor-content").first
                    if form.is_visible(timeout=2000):
                        result["error"] = "表单仍可见，发布未成功"
                except:
                    pass
                if not result["error"]:
                    resolved_url = resolved_url or resolve_answer_url(page, question_url, wait_sec=10)
                    if not resolved_url:
                        result["error"] = f"Answer URL not resolved after publish; current URL is {cur_url}"
                        browser.close()
                        return result
                    cur_url = resolved_url
                    result["success"] = True
                    result["url"] = cur_url
                    print(f"  [LIKELY OK] 表单消失，URL: {cur_url}")
            
        except Exception as e:
            result["error"] = f"异常: {e}"
            import traceback
            traceback.print_exc()
        finally:
            if browser:
                try:
                    browser.close()
                except:
                    pass
    
    return result


def main():
    setup_logging("publish_answer")
    parser = argparse.ArgumentParser()
    parser.add_argument("--q", help="Question URL")
    parser.add_argument("--file", help="Content file (answer_1.txt etc)")
    parser.add_argument("--image", help="Image path")
    parser.add_argument("--all", action="store_true", help="Publish all answer files")
    parser.add_argument("--max", type=int, default=999, help="Max answers to publish")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Ignore publish log")
    args = parser.parse_args()
    
    log = load_log()
    results = {"ok": 0, "fail": 0, "skip": 0}
    
    if args.all:
        answers_dir = ROOT / "answers"
        files = sorted(answers_dir.glob("answer_*.txt"))
        files = files[:args.max]
        print(f"[ALL] {len(files)} answer files found, max={args.max}")
        
        for fpath in files:
            fname = fpath.name
            if not args.force and is_published(log, fname):
                results["skip"] += 1
                print(f"\n[SKIP] {fname} (already published today)")
                continue
            
            text = fpath.read_text(encoding="utf-8").strip()
            if not text:
                results["fail"] += 1
                print(f"\n[FAIL] {fname}: 空文件")
                continue
            
            lines = text.split("\n")
            question_url = lines[0].strip()
            content = "\n".join(lines[2:]) if len(lines) > 2 else ""
            
            if not content.strip():
                results["fail"] += 1
                print(f"\n[FAIL] {fname}: 无内容")
                continue
            
            # 匹配配图
            stem = fpath.stem
            imgs = sorted(IMAGES_DIR.glob(f"{stem}_img*.png"))
            img_path = imgs[0] if imgs else None
            
            r = publish_answer(question_url, content, img_path, args.dry_run)
            if r["success"]:
                results["ok"] += 1
                mark_published(log, fname, r["url"], fname)
            else:
                results["fail"] += 1
                print(f"  [FAIL] {r['error']}")
            
            time.sleep(random.uniform(45, 90))
    
    elif args.q and args.file:
        fpath = Path(args.file)
        text = fpath.read_text(encoding="utf-8").strip()
        if not text:
            print("[FAIL] 空文件")
            return
        
        lines = text.split("\n")
        question_url = lines[0].strip() or args.q
        content = "\n".join(lines[2:]) if len(lines) > 2 else ""
        
        r = publish_answer(question_url, content, args.image, args.dry_run)
        if r["success"]:
            results["ok"] += 1
            mark_published(log, fpath.name, r["url"], fpath.name)
        else:
            results["fail"] += 1
    else:
        print("Usage: publish_answer_v11.py --q URL --file FILE [--image IMG]")
        print("   or: publish_answer_v11.py --all [--max N] [--force] [--dry-run]")
        return
    
    print(f"\n[SUMMARY] ok={results['ok']} fail={results['fail']} skip={results['skip']}")


if __name__ == "__main__":
    main()

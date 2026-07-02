#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish_article_v4.py - 知乎文章发布（支持配图上传）
基于 v3 验证通过的图片上传流程：
  点击图片按钮 → set_input_files → 等待8秒 → img出现在编辑器中

用法：
  python publish_article_v4.py --file articles/xxx.txt              # 发布指定文件
  python publish_article_v4.py --file articles/xxx.txt --images img1.png,img2.png  # 指定配图文件
  python publish_article_v4.py --all                                # 发布所有
  python publish_article_v4.py --dry-run                            # 模拟运行

内容格式要求：
  第一行：标题（纯文字）
  空行后：正文（可包含 【配图N：描述】 占位符）

示例文章内容：
  外贸人常用的10个偷懒工具

  **结论先说：工具用对了，每天至少省2小时。**
  
  下面这10个工具...
  
  【配图1：外贸工具全景图】
  
  ### 二、聊客户阶段
  ...
"""

import json, re, sys, time, random, argparse
import logging
from contextlib import nullcontext
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from zhihu_publish_common import (
    ARTICLES_DIR,
    DEBUG_DIR,
    IMAGES_DIR,
    LOG_FILE,
    PROJECT_ROOT,
    cookie_file,
    confirm_or_continue,
    ensure_logged_in,
    load_cookies_with_refresh,
    load_log,
    mark_published as common_mark_published,
    setup_logging,
    validate_content,
    wait_for_editor,
)


# ── 路径配置 ────────────────────────────────────────
ROOT = PROJECT_ROOT
COOKIE_FILE = cookie_file()
BASE_URL = "https://zhuanlan.zhihu.com"

# 配图占位符正则
IMAGE_PLACEHOLDER_RE = re.compile(r'【配图\s*(\d+)[:：]\s*(.+?)】')


# ── 工具函数 ────────────────────────────────────────

def load_cookies(context) -> bool:
    return load_cookies_with_refresh(context)
    if not COOKIE_FILE.exists():
        print(f"[ERROR] Cookie 不存在: {COOKIE_FILE}")
        return False
    with open(COOKIE_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    context.add_cookies(cookies)
    return True


def load_log():
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            print(f"[WARN] publish_log.json 损坏 ({e})，备份为 .bak 后重置")
            try:
                bak = LOG_FILE.with_suffix(".json.bak")
                LOG_FILE.rename(bak)
                print(f"       已备份到 {bak.name}")
            except:
                pass
    return {"articles": {}, "answers": {}, "last_run": None}


def save_log(log):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


class NoopBrowser:
    def close(self):
        pass


def is_already_published(filename: str) -> bool:
    log = load_log()
    return filename in log.get("articles", {})


def mark_published(entry_type: str, filename: str, url: str, title: str):
    # 跳过临时文件（由 daily_publish_v2.py 调用时写入），避免垃圾条目
    if filename.startswith("tmp_"):
        return
    log = load_log()
    log[entry_type][filename] = {
        "url": url,
        "title": title,
        "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    log["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_log(log)


def take_screenshot(page, name):
    DEBUG_DIR.mkdir(exist_ok=True)
    try:
        path = DEBUG_DIR / f"{name}_{int(time.time())}.png"
        page.screenshot(path=str(path))
        print(f"       [DEBUG] 截图已保存: {path.name}")
    except Exception as e:
        print(f"       [WARN] 截图失败: {e}")


# ── 内容解析 ────────────────────────────────────────

def parse_content_with_images(content: str, has_images: bool = True):
    """
    解析含【配图N】占位符的内容。
    返回 segments 列表：
      [
        {"type": "text", "content": "..."},
        {"type": "image", "index": 1, "desc": "外贸工具全景图"},
        {"type": "text", "content": "..."},
        ...
      ]
    当 has_images=False 时，自动剔除【配图N】占位符文本（不生成image段）
    """
    segments = []
    last_end = 0
    for m in IMAGE_PLACEHOLDER_RE.finditer(content):
        # 添加前面的文本
        text_before = content[last_end:m.start()].strip('\n')
        if text_before:
            segments.append({"type": "text", "content": text_before})

        if has_images:
            # 有配图：创建 image 段，后续会上传图片替换
            idx = int(m.group(1))
            desc = m.group(2).strip()
            segments.append({"type": "image", "index": idx, "desc": desc})
        # else: 无配图 → 直接剔除占位符文本，不生成段

        last_end = m.end()

    # 最后一段文本
    remaining = content[last_end:].strip('\n')
    if remaining:
        segments.append({"type": "text", "content": remaining})

    return segments


def resolve_image_files(image_list: list, images_dir: Path = IMAGES_DIR):
    """
    将 image_list（文件名或路径列表）解析为完整路径列表。
    返回 [Path, ...]
    """
    resolved = []
    for item in image_list:
        p = Path(item)
        if p.is_absolute() and p.exists():
            resolved.append(p)
        else:
            candidate = images_dir / p.name if p.suffix else None
            if candidate and candidate.exists():
                resolved.append(candidate)
            else:
                # 在 images_dir 里找匹配的文件
                found = False
                for ext in ['.png', '.jpg', '.jpeg', '.webp']:
                    fp = images_dir / (p.stem + ext) if p.suffix else images_dir / (item + ext)
                    if fp.exists():
                        resolved.append(fp)
                        found = True
                        break
                if not found:
                    resolved.append(None)  # 标记为找不到
    return resolved


# ── 编辑器操作 ──────────────────────────────────────

def type_text_slow(page, text: str, delay: int = 5):
    """慢速输入，模拟人工"""
    total = len(text)
    chunk_size = 100
    pos = 0
    while pos < total:
        part = text[pos:pos+chunk_size]
        page.keyboard.type(part, delay=random.randint(delay-2, delay+2))
        time.sleep(random.uniform(0.1, 0.3))
        pos += chunk_size
        if pos % 800 == 0 and pos > 0:
            pct = min(100, round(pos/total*100))
            print(f"     [{pct}%] 已输入 {pos}/{total}")


def find_editor(page, prefer_body=True):
    """找到正文编辑器（确保是正文区而非标题区）"""
    editors = page.locator(".public-DraftEditor-content").all()
    if len(editors) >= 2:
        return editors[1] if prefer_body else editors[0]
    elif editors:
        # 只有 1 个编辑器时，验证高度（正文编辑器 > 200px，标题 ~50px）
        try:
            box = editors[0].bounding_box()
            if box and box["height"] > 200:
                return editors[0]
            print(f"  [WARN] 仅找到1个编辑器(h={box['height'] if box else '?'}px)，可能不是正文区")
        except:
            pass
        return editors[0]  # 回退：仍返回这个（有总比没有好）

    # fallback: 找大的 contenteditable
    for sel in ["[contenteditable='true']", "textarea"]:
        candidates = page.locator(sel).all()
        for c in candidates:
            box = c.bounding_box()
            if box and box["height"] > 200:
                return c
    return None


def click_image_button(page):
    """点击编辑器工具栏的「图片」按钮"""
    btn = page.locator("button[aria-label='图片']").first
    btn.is_visible(timeout=5000)
    # 用force点击，绕过可能的Modal-backdrop遮挡
    btn.click(force=True)
    time.sleep(random.uniform(1.5, 2.5))
    return True


def close_upload_modal(page):
    """关闭可能残留的图片上传弹窗/遮罩层，返回 True 表示弹窗已消失"""
    closed = False
    
    # 方法1: 点ESC键关闭弹窗
    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
        closed = True
    except:
        pass

    try:
        # 方法2: 点击遮罩层外部区域（如果有的话）
        backdrop = page.locator(".Modal-backdrop").first
        if backdrop.count() > 0 and backdrop.is_visible(timeout=500):
            page.keyboard.press("Escape")
            time.sleep(0.5)
            closed = True
    except:
        pass

    # 方法3: 关闭按钮（X / Close）
    if not closed:
        try:
            for sel in ["button[aria-label='Close']", "button[aria-label='close']",
                         ".Modal button:last-child", "[class*='close']"]:
                try:
                    cb = page.locator(sel).first
                    if cb.is_visible(timeout=500):
                        cb.click(force=True)
                        time.sleep(0.5)
                        closed = True
                        break
                except:
                    continue
        except:
            pass

    # 方法4: 验证弹窗是否还在（检查 Modal-backdrop 可见性）
    if not closed:
        try:
            backdrop = page.locator(".Modal-backdrop").first
            if backdrop.count() == 0 or not backdrop.is_visible(timeout=300):
                closed = True  # 没有遮罩层 → 弹窗已关
        except:
            pass

    return closed


def upload_image_to_editor(page, image_path: Path) -> bool:
    """
    上传一张图片到知乎编辑器。
    流程（已验证）：
    1. 找到 accept 包含 'image' 的 hidden file input
    2. set_input_files(image_path)
    3. 等待上传完成（~8秒）
    4. 验证 <img> 出现在编辑器中
    """
    if not image_path or not image_path.exists():
        print(f"       ✗ 图片不存在: {image_path}")
        return False

    print(f"       ↑ 上传 {image_path.name} ({image_path.stat().st_size/1024:.1f}KB)")

    # 找图片专用的 file input
    inputs = page.locator("input[type='file'][accept*='image']")
    if inputs.count() == 0:
        inputs = page.locator("input[type='file']")

    uploaded = False
    for i in range(inputs.count()):
        fi = inputs.nth(i)
        try:
            accept = fi.get_attribute("accept") or ""
            fi.set_input_files(str(image_path))
            uploaded = True
            break
        except Exception as e:
            continue

    if not uploaded:
        print(f"       ✗ set_input_files 失败")
        take_screenshot(page, "v4_img_upload_fail")
        return False

    # 等待上传完成
    print(f"       ⏳ 等待上传...", end="", flush=True)

    # 先快速检查是否需要确认按钮
    time.sleep(2)
    try:
        confirm_btns = [
            'button:text-is("请选择文件")',
            'button:has-text("请选择文件")',
            'button:text-is("确定")',
            'button:has-text("确定")',
            'button:has-text("上传")',
        ]
        for sel in confirm_btns:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=800):
                    txt = btn.inner_text(timeout=300).strip()
                    print(f"\n       → 点击确认 '{txt}'")
                    btn.click()
                    time.sleep(1)
                    break
            except:
                continue
    except Exception:
        pass

    # 主等待循环
    max_wait = 15  # 最长等15秒
    start = time.time()
    while time.time() - start < max_wait:
        time.sleep(2)
        elapsed = int(time.time() - start)
        has_image = page.evaluate("""() => {
            const eds = document.querySelectorAll('.public-DraftEditor-content');
            for (const e of eds) {
                if (e.innerHTML.includes('<img')) return true;
            }
            return false;
        }""")
        print(f"{elapsed}s", end="", flush=True)
        if has_image:
            print(f" ✓ ({elapsed}s)")
            return True

    print(f" ✗ ({max_wait}s)")
    take_screenshot(page, "v4_img_timeout")
    return False


def upload_image_with_retry(page, image_path: Path, attempts: int = 3) -> bool:
    for attempt in range(1, attempts + 1):
        logging.info("Uploading image attempt %s/%s: %s", attempt, attempts, image_path)
        if upload_image_to_editor(page, image_path):
            return True
        close_upload_modal(page)
        if attempt < attempts:
            time.sleep(2 * attempt)
            try:
                click_image_button(page)
            except Exception:
                logging.debug("Re-open image modal failed", exc_info=True)
    return False


def input_title(page, title: str):
    """输入标题"""
    for sel in ["textarea", "input[class*='Input']", "[class*='TitleInput'] textarea"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                time.sleep(0.3)
                el.fill(title)
                print(f"  [OK] 标题输入成功")
                return True
        except:
            continue

    # Draft.js fallback
    editors = page.locator(".public-DraftEditor-content").all()
    if editors:
        editors[0].click(); time.sleep(0.3); page.keyboard.type(title, delay=3)
        print("  [OK] 标题(Draft.js)")
        return True

    print("  [WARN] 标题未输入")
    return False


# ── 核心发布逻辑 ────────────────────────────────────

def publish_article_with_images(
    title: str,
    content: str,
    image_paths: list = None,
    dry_run: bool = False,
    file_stem: str = None,
    shared_context=None,
) -> dict:
    """
    发布一篇知乎文章（支持配图）。
    """
    warnings = validate_content(content, "articles")
    if not confirm_or_continue(warnings, assume_yes=dry_run):
        return {"success": False, "url": None, "error": "Stopped by content validation warnings"}

    if dry_run:
        segments = parse_content_with_images(content, has_images=bool(image_paths))
        n_images = sum(1 for s in segments if s['type'] == 'image')
        print(f"[DRY-RUN] {title[:50]}... (正文{len(content)}字, {len(segments)}段, {n_images}张配图)")
        return {"success": True, "url": "dry-run"}

    result = {"success": False, "url": None, "error": None}
    segments = parse_content_with_images(content, has_images=bool(image_paths))
    n_images = sum(1 for s in segments if s['type'] == 'image')
    n_texts = sum(1 for s in segments if s['type'] == 'text')

    # 检测：内容中有占位符但没提供配图文件
    n_placeholders = len(IMAGE_PLACEHOLDER_RE.findall(content))
    if n_placeholders > 0 and not image_paths:
        print(f"  [WARN] 内容含 {n_placeholders} 个【配图】占位符，但未提供配图文件 → 占位符文本已自动剔除")

    print(f"\n{'='*60}")
    print(f"[ARTICLE] {title[:60]}")
    print(f"[INFO] 正文 {len(content)} 字 | {n_texts} 个文本段 | {n_images} 张配图")
    print(f"{'='*60}")

    # 准备图片路径映射
    image_map = {}  # index -> Path
    if image_paths:
        resolved = resolve_image_files(image_paths)
        for i, rp in enumerate(resolved):
            image_map[i+1] = rp
    else:
        # 尝试从 image_tracker.json 加载（过滤到当前文章）
        tracker_file = ROOT / "image_tracker.json"
        if tracker_file.exists():
            try:
                tracker = json.load(open(tracker_file, encoding='utf-8'))
                for k, v in tracker.get('images', {}).items():
                    # 过滤：仅加载属于当前文章的配图（精确匹配文件名，避免 article_1 误匹配 article_10）
                    tracker_file_name = v.get('file', '')
                    if file_stem and tracker_file_name and tracker_file_name != file_stem + '.txt':
                        continue
                    p = Path(v.get('image_path') or v.get('local_path') or '')
                    if not p.is_absolute():
                        p = ROOT / p
                    if p.exists():
                        # 从 key 中提取 index（如 answer_answer_1_img1 → 1）
                        idx_match = re.search(r'_img(\d+)$', k)
                        idx = int(idx_match.group(1)) if idx_match else 1
                        image_map[idx] = p
            except:
                pass

    with (nullcontext() if shared_context else sync_playwright()) as pw:
        if shared_context:
            browser = NoopBrowser()
            context = shared_context
        else:
            browser = pw.chromium.launch(
                headless=False,
                slow_mo=50,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                ]
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                locale="zh-CN",
            )

        try:
            cookies_ok = load_cookies(context)
        except Exception as e:
            cookies_ok = False
            result["error"] = f"Cookie 加载异常: {e}"
        if not cookies_ok:
            if not result["error"]:
                result["error"] = "Cookie 不存在或已失效"
            browser.close()
            return result

        page = context.new_page()

        try:
            # 1. 打开写文章页
            print("[1/6] 打开写文章页...")
            page.goto(f"{BASE_URL}/write", wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(3, 5))

            if "signin" in page.url or "login" in page.url:
                if ensure_logged_in(page, context):
                    page.goto(f"{BASE_URL}/write", wait_until="domcontentloaded", timeout=30000)
                    time.sleep(random.uniform(3, 5))
                else:
                    result["error"] = "Cookie refresh failed"
                    browser.close()
                    return result
            if "signin" in page.url or "login" in page.url:
                result["error"] = "Cookie 已失效，请重新运行 zhihu_auth.py"
                browser.close()
                return result
            print(f"  [OK] {page.url}")

            # 2. 输入标题
            print("[2/6] 输入标题...")
            if not input_title(page, title):
                print("  [WARN] 标题输入失败（继续发布，可能为空标题）")
                take_screenshot(page, "v4_no_title")
            time.sleep(1)

            # 3. 找到并点击正文编辑器
            print("[3/6] 定位正文编辑器...")
            try:
                editor = wait_for_editor(page, prefer_body=True)
            except TimeoutError as e:
                editor = None
                result["error"] = str(e)
            if not editor:
                result["error"] = "未找到正文编辑器"
                browser.close()
                return result
            editor.click()
            time.sleep(0.5)
            print(f"  [OK] 正文编辑器就绪")

            # 4. 输入正文（逐段，遇到图片则插入）
            print(f"[4/6] 输入正文 + 插入配图...")
            image_counter = 0
            seg_idx = 0
            for seg in segments:
                seg_idx += 1
                if seg['type'] == 'text':
                    print(f"     [文本段 {seg_idx}] 输入 {len(seg['content'])} 字...")
                    type_text_slow(page, seg['content'], delay=5)

                    # 如果下一段是图片，加个换行
                    next_is_image = seg_idx < len(segments) and segments[seg_idx]['type'] == 'image'
                    if next_is_image:
                        page.keyboard.press("Enter")
                        page.keyboard.press("Enter")
                        time.sleep(0.5)

                elif seg['type'] == 'image':
                    img_index = seg.get('index', image_counter + 1)
                    img_desc = seg.get('desc', '')
                    img_path = image_map.get(img_index)

                    if not img_path:
                        print(f"     [图片 {seg_idx}] ⚠️ 未提供图片文件 (index={img_index}, desc={img_desc})")
                        # 跳过这个图片，继续
                        continue

                    image_counter += 1
                    print(f"     [图片 {seg_idx}] #{img_index}: {img_desc}")

                    # 点击图片按钮
                    click_image_button(page)
                    # 上传图片
                    ok = upload_image_with_retry(page, img_path)
                    if ok:
                        print(f"     ✓ 配图#{image_counter} 插入成功")
                        # 关闭可能残留的上传弹窗，避免遮挡后续操作
                        closed = close_upload_modal(page)
                        if not closed:
                            print(f"     [WARN] 上传弹窗可能未关闭（继续尝试发布）")
                        time.sleep(0.5)
                    else:
                        result["error"] = f"Image upload failed after retries: {img_path}"
                        take_screenshot(page, "v4_img_upload_abort")
                        browser.close()
                        return result
                        print(f"     ✗ 配图#{image_counter} 插入失败（继续后续内容）")

                    # 图片后面可能需要换行继续文字
                    time.sleep(0.5)

            print(f"  [OK] 全部输入完成 ({image_counter}/{n_images} 张图片)")

            # 人为停顿（防检测）
            pause = random.uniform(3, 6)
            print(f"     ⏳ 人为停顿 {pause:.1f}s...")
            time.sleep(pause)

            # 5. 点击发布
            print("[5/6] 点击发布...")
            pub_clicked = False

            # 先滚动到底部，确保发布按钮在可视区
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(random.uniform(1, 2))

            # 方法1: JS精确匹配（不限制offsetParent）
            js_submit = """() => {
                const strip = (s) => (s||'').replace(/[\\u200b\\u200c\\u200d\\uFEFF]/g, '').trim();
                const btns = document.querySelectorAll('button');
                // 精确匹配：发布文章 / 提交修改（编辑模式）
                for (const b of btns) {
                    const t = strip(b.textContent);
                    if (t === '发布文章' || t === '提交修改') {
                        b.scrollIntoView({block:'center'}); b.click(); return 'clicked:'+t;
                    }
                }
                // 宽泛匹配：包含"发布"且非上传类按钮
                for (const b of btns) {
                    const t = strip(b.textContent);
                    if ((t.includes('发布') || t.includes('提交')) && t.length < 15) {
                        const cls = (b.className||'').toLowerCase();
                        if (!cls.includes('upload') && !cls.includes('picture')) {
                            b.scrollIntoView({block:'center'}); b.click(); return 'clicked:'+t;
                        }
                    }
                }
                return null;
            }"""
            r = page.evaluate(js_submit)
            if r:
                pub_clicked = True
                print(f"  [OK] {r}")

            # 方法2: Playwright locator + force
            if not pub_clicked:
                for sel in [
                    "button:has-text('发布文章')",
                    "button:has-text('提交修改')",
                    "button.Button--primary:has-text('发布')",
                    "[data-za-detail-view-element_name='Submit']",
                ]:
                    try:
                        btn = page.locator(sel).first
                        if btn.count() > 0:
                            btn.scroll_into_view_if_needed()
                            time.sleep(0.8)
                            btn.click(force=True)
                            pub_clicked = True
                            print(f"  [OK] force-click: {sel}")
                            break
                    except:
                        continue

            if not pub_clicked:
                result["error"] = "未找到发布按钮"
                take_screenshot(page, "v4_no_pub_btn")
                browser.close()
                return result

            # 二次确认弹窗
            time.sleep(2)
            try:
                confirm = page.locator("button:has-text('确认'), button:has-text('确定'), "
                                       "button:has-text('发布到专栏')").first
                if confirm.is_visible(timeout=3000):
                    print("  [INFO] 二次确认 → 点击")
                    confirm.click()
                    time.sleep(1)
            except:
                pass

            # 6. 等待跳转
            print("[6/6] 等待结果...")
            time.sleep(3)

            current_url = page.url
            if "/p/" in current_url or "zhuanlan.zhihu.com/p/" in current_url:
                result["success"] = True
                result["url"] = current_url
            else:
                try:
                    page.wait_for_url(lambda u: "/p/" in u or "zhuanlan" in u, timeout=12000)
                    result["success"] = True
                    result["url"] = page.url
                except PWTimeout:
                    result["error"] = "发布后未检测到跳转"
                    take_screenshot(page, "v4_post_pub")

            if result["success"]:
                print(f"\n  {'='*50}")
                print(f"  [SUCCESS] 文章发布成功!")
                print(f"  [LINK]    {result['url']}")
                print(f"  {'='*50}")
            else:
                print(f"  [FAIL] {result['error']}")

        except PWTimeout as e:
            result["error"] = f"页面超时: {e}"
            take_screenshot(page, "v4_timeout")
        except Exception as e:
            result["error"] = f"异常: {e}"
            take_screenshot(page, "v4_error")
        finally:
            browser.close()

    return result


# ── 主入口 ──────────────────────────────────────────

def main():
    setup_logging("publish_article")
    parser = argparse.ArgumentParser(description="知乎文章发布（支持配图）")
    parser.add_argument("--file", help="指定发布文件")
    parser.add_argument("--all", action="store_true", help="发布所有")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行")
    parser.add_argument("--force", action="store_true", help="强制重发")
    parser.add_argument("--images", help="配图文件列表（逗号分隔），如: img1.png,img2.png")
    args = parser.parse_args()

    ARTICLES_DIR.mkdir(exist_ok=True)
    IMAGES_DIR.mkdir(exist_ok=True)

    # 解析图片参数
    image_paths = []
    if args.images:
        image_paths = [p.strip() for p in args.images.split(',') if p.strip()]

    # 收集文件
    files = []
    if args.file:
        fp = Path(args.file)
        files.append(fp) if fp.exists() else print(f"[ERROR] {fp} 不存在")
    elif args.all:
        files = sorted(ARTICLES_DIR.glob("*.txt"))
    else:
        files = sorted(ARTICLES_DIR.glob("*.txt"))

    if not files:
        print("[INFO] 无待发布文件"); sys.exit(0)

    # 过滤已发布
    to_publish = []
    for fp in files:
        if not args.force and is_already_published(fp.name):
            log = load_log()
            info = log["articles"][fp.name]
            print(f"[SKIP] {fp.name} 已发: {info['url']}")
        else:
            to_publish.append(fp)

    if not to_publish:
        print("[INFO] 所有已发布"); sys.exit(0)

    print(f"\n[INFO] 待发布 {len(to_publish)} 篇")
    if image_paths:
        resolved = resolve_image_files(image_paths)
        names = [p.name for p in resolved if p is not None]
        print(f"[INFO] 配图: {names}")

    # 逐篇发布
    success_count = fail_count = 0
    for i, fp in enumerate(to_publish, 1):
        print(f"\n{'#'*60}\n# [{i}/{len(to_publish)}] {fp.name}\n{'#'*60}")

        title, content = read_article(fp)
        r = publish_article_with_images(title, content, image_paths=image_paths, dry_run=args.dry_run, file_stem=fp.stem)

        if r["success"]:
            mark_published("articles", fp.name, r["url"], title)
            success_count += 1
        else:
            print(f"  [FAIL] {r['error']}")
            fail_count += 1

        if i < len(to_publish):
            w = random.uniform(30, 60) if not args.dry_run else 1
            print(f"\n[WAIT] {int(w)}s..."); time.sleep(w)

    print(f"\n{'='*60}\n[SUMMARY] 成功:{success_count} 失败:{fail_count}\n{'='*60}")


def read_article(filepath: Path):
    """解析文章文件。返回 (title, content)，空文件返回空字符串并警告"""
    text = filepath.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or not any(l.strip() for l in lines):
        print(f"  [WARN] 文件为空: {filepath.name}")
        return "", ""
    title = lines[0].strip() if lines else ""
    body_start = 1
    for i, line in enumerate(lines[1:], 1):
        if line.strip():
            body_start = i; break
    content = "\n".join(lines[body_start:]) if body_start < len(lines) else ""
    return title, content


if __name__ == "__main__":
    main()

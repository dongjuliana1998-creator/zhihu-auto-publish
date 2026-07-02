#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_publish_v2.py - WADesk 知乎每日统一发布调度器 v2

支持：
- 文章发布（publish_article_v4.py，支持多张配图）
- 回答发布（publish_answer_v11.py，支持1张配图）
- 自动从文件名匹配配图（article_1.txt → images/article_1_img1.png, article_1_img2.png）
- 配图未完成时跳过图片上传，先发布纯文本
- 分批发布：--max-articles N --max-answers N

Usage:
  python daily_publish_v2.py                  # publish all
  python daily_publish_v2.py --max-articles 1 --max-answers 1  # 每批只发1篇
  python daily_publish_v2.py --articles-only
  python daily_publish_v2.py --answers-only
  python daily_publish_v2.py --dry-run
  python daily_publish_v2.py --stats
  python daily_publish_v2.py --force          # skip already-published check
"""

import sys
import time
import random
import argparse
from pathlib import Path
from datetime import datetime
from zhihu_publish_common import (
    ANSWERS_DIR,
    ARTICLES_DIR,
    IMAGES_DIR,
    LOG_FILE,
    PROJECT_ROOT,
    browser_session,
    confirm_or_continue,
    is_published,
    load_log,
    mark_published,
    setup_logging,
    validate_content,
)

ROOT = PROJECT_ROOT

TODAY = datetime.now().strftime("%Y-%m-%d")


def find_images_for_article(article_file):
    """根据文章文件名查找对应的配图
    article_1.txt → images/article_1_img1.png, images/article_1_img2.png
    """
    stem = article_file.stem  # article_1
    imgs = sorted(IMAGES_DIR.glob(f"{stem}_img*.png"))
    return [str(p) for p in imgs]


def find_image_for_answer(answer_file):
    """根据回答文件名查找对应的配图
    answer_1.txt → images/answer_1_img1.png
    """
    stem = answer_file.stem  # answer_1
    imgs = sorted(IMAGES_DIR.glob(f"{stem}_img*.png"))
    return str(imgs[0]) if imgs else None


def get_python_cmd():
    """获取 Python 命令，优先使用 WorkBuddy 托管的 Python（确保 playwright 等依赖可用）"""
    import shutil, os
    # 尝试从环境变量获取
    env_py = os.environ.get("WORKBUDDY_PYTHON") or os.environ.get("PYTHON_BIN")
    if env_py and Path(env_py).exists():
        return env_py
    # 尝试固定路径（WorkBuddy 托管）
    candidates = [
        "C:/Users/Lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe",
        "C:/Users/Lenovo/.workbuddy/binaries/python/envs/default/bin/python.exe",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    # 回退到系统 PATH 中的 python
    py = shutil.which("python") or shutil.which("python3")
    if py:
        return py
    return "python"  # 最后尝试，让系统报清晰的错误


def publish_article_v4(title, content, image_paths=None, dry_run=False, file_stem=None, shared_context=None):
    from publish_article_v4 import publish_article_with_images

    return publish_article_with_images(
        title,
        content,
        image_paths=image_paths,
        dry_run=dry_run,
        file_stem=file_stem,
        shared_context=shared_context,
    )


def publish_answer_v11(question_url, content, image_path=None, dry_run=False, shared_context=None):
    from publish_answer_v11 import publish_answer

    return publish_answer(
        question_url,
        content,
        image_path=image_path,
        dry_run=dry_run,
        shared_context=shared_context,
    )


def print_banner():
    print(f"""
{'=' * 62}
    WADesk Zhihu Daily Publisher v2
    Date: {TODAY}
    Status: Starting...
{'=' * 62}
""")


def print_summary(article_results, answer_results, start_time):
    elapsed = (time.time() - start_time) / 60
    a_success = sum(1 for r in article_results if r.get("success"))
    a_fail = len(article_results) - a_success
    q_success = sum(1 for r in answer_results if r.get("success"))
    q_fail = len(answer_results) - q_success

    print(f"""
{'=' * 62}
  Summary
{'=' * 62}
  Articles: {a_success} ok, {a_fail} fail
  Answers:  {q_success} ok, {q_fail} fail
  Time:     {elapsed:.1f} min
{'=' * 62}

Published:
""")
    for i, r in enumerate(article_results):
        if r.get("success"):
            print(f"  [Article {i+1}] {r.get('url', '?')}")
    for i, r in enumerate(answer_results):
        if r.get("success"):
            print(f"  [Answer {i+1}] {r.get('url', '?')}")

    if a_fail > 0 or q_fail > 0:
        print(f"\nFailed:")
        for i, r in enumerate(article_results):
            if not r.get("success"):
                print(f"  [Article {i+1}] {r.get('error', '?')}")
        for i, r in enumerate(answer_results):
            if not r.get("success"):
                print(f"  [Answer {i+1}] {r.get('error', '?')}")
    print()


def show_stats():
    if not LOG_FILE.exists():
        print("[INFO] No publish log yet")
        return
    log = load_log()  # 使用带异常处理的 load_log，而非直接 json.loads
    articles = log.get("articles", {})
    answers = log.get("answers", {})
    print(f"\n{'='*50}\n  Publish Stats\n{'='*50}")
    print(f"  Articles: {len(articles)} published")
    for k, v in list(articles.items()):
        print(f"    [{v['published_at']}] {v['title'][:40]}")
        print(f"      {v['url']}")
    print(f"\n  Answers: {len(answers)} published")
    for k, v in list(answers.items()):
        print(f"    [{v['published_at']}] {v['title'][:40]}")
        print(f"      {v['url']}")
    print(f"\n  Last run: {log.get('last_run', 'N/A')}")


def main():
    setup_logging("daily_publish")
    parser = argparse.ArgumentParser(description="WADesk Zhihu Daily Publisher v2")
    parser.add_argument("--articles-only", action="store_true")
    parser.add_argument("--answers-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--force", action="store_true", help="Skip already-published check")
    parser.add_argument("--max-articles", type=int, default=0, help="Max articles to publish (0=all)")
    parser.add_argument("--max-answers", type=int, default=0, help="Max answers to publish (0=all)")
    args = parser.parse_args()

    ARTICLES_DIR.mkdir(exist_ok=True)
    ANSWERS_DIR.mkdir(exist_ok=True)

    if args.stats:
        show_stats()
        return

    print_banner()
    start_time = time.time()
    article_results = []
    answer_results = []

    SKIP_FILES = {"TEMPLATE.txt", "tmp_answer.txt", "tmp_article.txt"}
    session_cm = None
    shared_context = None

    def get_shared_context():
        nonlocal session_cm, shared_context
        if args.dry_run:
            return None
        if shared_context is None:
            session_cm = browser_session()
            shared_context = session_cm.__enter__()
        return shared_context

    # --- Publish Articles ---
    if not args.answers_only:
        log = load_log()  # 一次读取，避免列表推导中每文件读一次
        article_files = sorted([
            f for f in ARTICLES_DIR.glob("*.txt")
            if f.name not in SKIP_FILES
            and (args.force or not is_published(log, f.name))
        ])
        # 限制数量（分批发布）
        if args.max_articles > 0:
            article_files = article_files[:args.max_articles]
        if article_files:
            print(f"\n[PHASE 1] Articles ({len(article_files)} files)\n")
            for i, fp in enumerate(article_files, 1):
                print(f"[{i}/{len(article_files)}] {fp.name}")

                # 查找配图
                imgs = find_images_for_article(fp)
                if imgs:
                    print(f"  [IMG] Found {len(imgs)} image(s): {[Path(p).name for p in imgs]}")
                else:
                    print(f"  [IMG] No images found, publishing text only")

                # 读取标题和内容
                lines = fp.read_text(encoding="utf-8").splitlines()
                title = lines[0] if lines else fp.stem
                # 跳过标题后的空行（兼容有/无空行格式）
                body_start = 1
                while body_start < len(lines) and not lines[body_start].strip():
                    body_start += 1
                content = "\n".join(lines[body_start:]) if body_start < len(lines) else ""

                # 调用 v4 发布
                result = publish_article_v4(
                    title, content,
                    image_paths=imgs if imgs else None,
                    dry_run=args.dry_run,
                    file_stem=fp.stem,
                    shared_context=get_shared_context(),
                )
                article_results.append({"file": fp.name, "title": title, **result})

                if result["success"]:
                    print(f"  [OK] {result['url']}")
                    if not args.dry_run:
                        mark_published(log, fp.name, result["url"], title, "articles")
                else:
                    print(f"  [FAIL] {result.get('error', '?')}")

                if i < len(article_files) and not args.dry_run:
                    wait = random.uniform(45, 90)
                    print(f"\n  [WAIT] {int(wait)}s...")
                    time.sleep(wait)
        else:
            print("\n[INFO] No pending articles")

    # --- Publish Answers ---
    if not args.articles_only:
        log = load_log()
        answer_files = sorted([
            f for f in ANSWERS_DIR.glob("*.txt")
            if f.name not in SKIP_FILES
            and (args.force or not is_published(log, f.name))
        ])
        # 限制数量（分批发布）
        if args.max_answers > 0:
            answer_files = answer_files[:args.max_answers]
        if answer_files:
            print(f"\n[PHASE 2] Answers ({len(answer_files)} files)\n")
            for i, fp in enumerate(answer_files, 1):
                print(f"[{i}/{len(answer_files)}] {fp.name}")

                # 读取URL和内容
                lines = fp.read_text(encoding="utf-8").splitlines()
                q_url = lines[0] if lines else ""
                # 跳过 URL 后的空行（兼容有/无空行格式）
                body_start = 1
                while body_start < len(lines) and not lines[body_start].strip():
                    body_start += 1
                content = "\n".join(lines[body_start:]) if body_start < len(lines) else ""

                if not q_url or not q_url.startswith("http"):
                    print(f"  [SKIP] No valid question URL in file")
                    continue

                # 查找配图
                img = find_image_for_answer(fp)
                if img:
                    print(f"  [IMG] Found image: {Path(img).name}")
                else:
                    print(f"  [IMG] No image found, publishing text only")

                # 调用 v11 发布
                result = publish_answer_v11(
                    q_url, content,
                    image_path=img if img else None,
                    dry_run=args.dry_run,
                    shared_context=get_shared_context(),
                )
                answer_results.append({"file": fp.name, "title": fp.stem, **result})

                if result["success"]:
                    print(f"  [OK] {result['url']}")
                    if not args.dry_run:
                        mark_published(log, fp.name, result["url"], fp.name, "answers")
                else:
                    print(f"  [FAIL] {result.get('error', '?')}")

                if i < len(answer_files) and not args.dry_run:
                    wait = random.uniform(90, 150)
                    print(f"\n  [WAIT] {int(wait)}s...")
                    time.sleep(wait)
        else:
            print("\n[INFO] No pending answers")

    if session_cm:
        session_cm.__exit__(None, None, None)

    print_summary(article_results, answer_results, start_time)


if __name__ == "__main__":
    main()

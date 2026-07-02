#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_publish_v2.py - WADesk 知乎每日统一发布调度器 v2 (CODEX优化版)

支持：
- 文章发布（直接调用 publish_article_v4 模块，不再走 subprocess）
- 回答发布（直接调用 publish_answer_v11 模块，不再走 subprocess）
- 自动从文件名匹配配图（article_1.txt → images/article_1_img1.png, article_1_img2.png）
- 配图未完成时跳过图片上传，先发布纯文本
- 分批发布：--max-articles N --max-answers N
- 发布前内容校验（字数、禁止模式）

Usage:
  python scripts/daily_publish_v2.py                  # publish all
  python scripts/daily_publish_v2.py --max-articles 1 --max-answers 1  # 每批只发1篇
  python scripts/daily_publish_v2.py --articles-only
  python scripts/daily_publish_v2.py --answers-only
  python scripts/daily_publish_v2.py --dry-run
  python scripts/daily_publish_v2.py --stats
  python scripts/daily_publish_v2.py --force          # skip already-published check
"""

import sys
import time
import random
import argparse
from pathlib import Path
from datetime import datetime

# 从公共模块导入所有共享函数和常量
from zhihu_publish_common import (
    ANSWERS_DIR,
    ARTICLES_DIR,
    IMAGES_DIR,
    LOG_FILE,
    PROJECT_ROOT,
    confirm_or_continue,
    is_published,
    load_log,
    mark_published,
    setup_logging,
    validate_content,
)

ROOT = PROJECT_ROOT
TODAY = datetime.now().strftime("%Y-%m-%d")


# ─── 发布函数（直接 import 模块调用，不走 subprocess）───────────

def publish_article(title, content, image_paths=None, dry_run=False):
    """调用 publish_article_v4 模块发布文章"""
    # 将 cwd 设为 scripts/ 目录，让 publish_article_v4 能找到 zhihu_publish_common
    sys.path.insert(0, str(ROOT / "scripts"))
    from publish_article_v4 import publish_article_with_images
    return publish_article_with_images(
        title, content,
        image_paths=image_paths,
        dry_run=dry_run,
    )


def publish_answer(question_url, content, image_path=None, dry_run=False):
    """调用 publish_answer_v11 模块发布回答"""
    sys.path.insert(0, str(ROOT / "scripts"))
    from publish_answer_v11 import publish_answer
    return publish_answer(
        question_url, content,
        image_path=image_path,
        dry_run=dry_run,
    )


# ─── 辅助函数 ────────────────────────────────────────────────

def find_images_for_article(article_file):
    """根据文章文件名查找对应的配图
    article_1.txt → images/article_1_img1.png, images/article_1_img2.png
    """
    stem = article_file.stem
    imgs = sorted(IMAGES_DIR.glob(f"{stem}_img*.png"))
    return [str(p) for p in imgs]


def find_image_for_answer(answer_file):
    """根据回答文件名查找对应的配图
    answer_1.txt → images/answer_1_img1.png
    """
    stem = answer_file.stem
    imgs = sorted(IMAGES_DIR.glob(f"{stem}_img*.png"))
    return str(imgs[0]) if imgs else None


# ─── 显示函数 ────────────────────────────────────────────────

def print_banner():
    print(f"""
{'=' * 62}
    WADesk Zhihu Daily Publisher v2 (optimized)
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
        print("\nFailed:")
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
    log = load_log()
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


# ─── 主流程 ───────────────────────────────────────────────────

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

    # --- Publish Articles ---
    if not args.answers_only:
        log = load_log()
        article_files = sorted([
            f for f in ARTICLES_DIR.glob("*.txt")
            if f.name not in SKIP_FILES
            and (args.force or not is_published(log, f.name))
        ])
        if args.max_articles > 0:
            article_files = article_files[:args.max_articles]
        if article_files:
            print(f"\n[PHASE 1] Articles ({len(article_files)} files)\n")
            for i, fp in enumerate(article_files, 1):
                print(f"[{i}/{len(article_files)}] {fp.name}")

                imgs = find_images_for_article(fp)
                if imgs:
                    print(f"  [IMG] Found {len(imgs)} image(s): {[Path(p).name for p in imgs]}")
                else:
                    print(f"  [IMG] No images found, publishing text only")

                lines = fp.read_text(encoding="utf-8").splitlines()
                title = lines[0] if lines else fp.stem
                body_start = 1
                while body_start < len(lines) and not lines[body_start].strip():
                    body_start += 1
                content = "\n".join(lines[body_start:]) if body_start < len(lines) else ""

                # 发布前内容校验
                warnings = validate_content(content, "articles")
                if warnings and not args.dry_run:
                    for w in warnings:
                        print(f"  [WARN] {w}")
                    if not confirm_or_continue(warnings, assume_yes=args.dry_run):
                        print(f"  [SKIP] 用户取消发布")
                        continue

                result = publish_article(
                    title, content,
                    image_paths=imgs if imgs else None,
                    dry_run=args.dry_run,
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
        if args.max_answers > 0:
            answer_files = answer_files[:args.max_answers]
        if answer_files:
            print(f"\n[PHASE 2] Answers ({len(answer_files)} files)\n")
            for i, fp in enumerate(answer_files, 1):
                print(f"[{i}/{len(answer_files)}] {fp.name}")

                lines = fp.read_text(encoding="utf-8").splitlines()
                q_url = lines[0] if lines else ""
                body_start = 1
                while body_start < len(lines) and not lines[body_start].strip():
                    body_start += 1
                content = "\n".join(lines[body_start:]) if body_start < len(lines) else ""

                if not q_url or not q_url.startswith("http"):
                    print(f"  [SKIP] No valid question URL in file")
                    continue

                img = find_image_for_answer(fp)
                if img:
                    print(f"  [IMG] Found image: {Path(img).name}")
                else:
                    print(f"  [IMG] No image found, publishing text only")

                # 发布前内容校验
                warnings = validate_content(content, "answers")
                if warnings and not args.dry_run:
                    for w in warnings:
                        print(f"  [WARN] {w}")
                    if not confirm_or_continue(warnings, assume_yes=args.dry_run):
                        print(f"  [SKIP] 用户取消发布")
                        continue

                result = publish_answer(
                    q_url, content,
                    image_path=img if img else None,
                    dry_run=args.dry_run,
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

    print_summary(article_results, answer_results, start_time)


if __name__ == "__main__":
    main()

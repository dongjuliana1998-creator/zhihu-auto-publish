#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
manage_images.py - 知乎内容配图管理器

功能：
  1. 扫描 articles/ 和 answers/ 中的图片占位符
  2. 生成 ImageGen 提示词
  3. 跟踪已生成/未生成的图片
  4. 列出每篇内容的配图状态

用法：
  python manage_images.py --scan          # 扫描所有内容，输出配图清单
  python manage_images.py --prompts       # 输出所有待生成图片的 ImageGen prompt
  python manage_images.py --status        # 查看配图状态
  python manage_images.py --mark-done ID  # 标记某张图已生成
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent
ARTICLES_DIR = ROOT / "articles"
ANSWERS_DIR = ROOT / "answers"
IMAGES_DIR = ROOT / "images"
TRACKER_FILE = ROOT / "image_tracker.json"

IMAGES_DIR.mkdir(exist_ok=True)


def load_tracker():
    if TRACKER_FILE.exists():
        try:
            return json.loads(TRACKER_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] image_tracker.json 损坏 ({e})，备份后重置")
            try:
                bak = TRACKER_FILE.with_suffix(".json.bak")
                TRACKER_FILE.rename(bak)
                print(f"       已备份到 {bak.name}")
            except:
                pass
    return {"images": {}, "last_scan": None}


def save_tracker(tracker):
    tracker["last_scan"] = datetime.now().isoformat()
    TRACKER_FILE.write_text(json.dumps(tracker, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_placeholders(text):
    """Extract 【配图 N：xxx】 from text."""
    pattern = r'【配图\s*(\d+)[：:](.+?)】'
    return re.findall(pattern, text)


def extract_image_suggestions(text):
    """Extract image suggestions from 配图建议 section."""
    # Look for 配图建议 section after the main content
    suggestions = []
    in_section = False
    lines = text.split('\n')
    current = {}

    for line in lines:
        if '配图建议' in line or '## 配图' in line:
            in_section = True
            continue
        if in_section:
            if line.startswith('【配图'):
                if current:
                    suggestions.append(current)
                current = {"id": line.strip()}
            elif '位置' in line or 'Position' in line:
                current['position'] = line.strip()
            elif '主题' in line or 'Topic' in line:
                current['topic'] = line.strip()
            elif '画面' in line or 'Scene' in line:
                current['scene'] = line.strip()
            elif '图中文字' in line or 'Text' in line:
                current['text_overlay'] = line.strip()
            elif '素材' in line or 'Type' in line:
                current['type'] = line.strip()
            elif line.strip() == '' and current:
                suggestions.append(current)
                current = {}

    if current:
        suggestions.append(current)

    return suggestions


def scan_content(file_path, content_type):
    """Scan a single content file and return image info."""
    text = file_path.read_text(encoding="utf-8")
    placeholders = extract_placeholders(text)
    suggestions = extract_image_suggestions(text)

    results = []
    for num, desc in placeholders:
        img_id = f"{content_type}_{file_path.stem}_img{num}"
        results.append({
            "id": img_id,
            "file": str(file_path.name),
            "type": content_type,
            "num": int(num),
            "description": desc.strip(),
            "placeholder": f"【配图 {num}：{desc.strip()}】"
        })

    return results, suggestions


def scan_all():
    """Scan all content files for image placeholders."""
    all_images = []

    for fp in sorted(ARTICLES_DIR.glob("*.txt")):
        if fp.name == "TEMPLATE.txt":
            continue
        imgs, suggestions = scan_content(fp, "article")
        all_images.extend(imgs)

    for fp in sorted(ANSWERS_DIR.glob("*.txt")):
        if fp.name == "TEMPLATE.txt":
            continue
        imgs, suggestions = scan_content(fp, "answer")
        all_images.extend(imgs)

    return all_images


def generate_prompts(images):
    """Generate ImageGen prompts for each image."""
    prompts = []
    for img in images:
        prompt = _build_image_prompt(img)
        prompts.append({"id": img["id"], "file": img["file"], "prompt": prompt})
    return prompts


def _build_image_prompt(img):
    """Build an optimized ImageGen prompt from placeholder description."""
    desc = img["description"]

    # Map common patterns to better ImageGen prompts
    if "客户" in desc and ("流失" in desc or "资产" in desc):
        return (
            f"A simple, clean flowchart or funnel diagram showing how customer assets get lost "
            f"in a sales team. Shows a smartphone with WhatsApp icon connected to a salesperson icon, "
            f"then an arrow pointing to '客户关系留在个人手机'. "
            f"Modern infographic style, red-to-green gradient, Chinese text, "
            f"clean white background. Professional but accessible."
        )
    elif ("多账号" in desc) or ("WhatsApp" in desc and "管理" in desc):
        return (
            f"A clean dashboard-style illustration showing multiple WhatsApp account icons "
            f"being centrally managed through a single interface. "
            f"Shows chat logs, customer tags, team permissions flowing into one unified workspace. "
            f"Modern SaaS-style UI illustration, blue and teal color scheme, "
            f"clean, professional, suitable for a tech business article."
        )
    elif "飞单" in desc:
        return (
            f"A conceptual diagram illustrating the risk of '飞单' (salesperson taking clients away) "
            f"in a business context. Shows a salesperson holding a phone with customer data, "
            f"with a warning symbol. Contrast with a team-managed CRM system. "
            f"Clean infographic style, Chinese text labels, professional look."
        )
    elif "销售" in desc and ("链路" in desc or "流程" in desc):
        return (
            f"A professional sales process flowchart or comparison diagram showing "
            f"the sales journey for different product types. "
            f"Clean, modern infographic design with icons and arrows, "
            f"Chinese text labels, blue and orange accent colors, white background."
        )
    else:
        # Generic prompt based on description
        return (
            f"A professional, clean infographic or diagram about: {desc}. "
            f"Modern flat design style, Chinese and English text where appropriate, "
            f"blue and orange color accents, clean white background, "
            f"suitable for a Chinese business and technology article on Zhihu. "
            f"No photorealistic elements, no stock photo look."
        )


def cmd_scan():
    """Scan and show all image placeholders."""
    images = scan_all()
    if not images:
        print("[INFO] No image placeholders found in any content files.")
        return

    tracker = load_tracker()
    generated = {k: v for k, v in tracker["images"].items() if v.get("generated")}

    print(f"\n{'='*60}")
    print(f"  Image Placeholder Scan")
    print(f"{'='*60}")
    print(f"  Total placeholders: {len(images)}")
    print(f"  Generated: {len(generated)}")
    print(f"  Pending: {len(images) - len(generated)}")
    print()

    by_file = {}
    for img in images:
        f = img["file"]
        if f not in by_file:
            by_file[f] = []
        by_file[f].append(img)

    for filename, imgs in by_file.items():
        print(f"  [{filename}]")
        for img in imgs:
            status = "[OK]" if img["id"] in generated else "[  ]"
            print(f"    {status} 配图 {img['num']}: {img['description'][:60]}")
        print()

    # Update tracker with newly found images
    for img in images:
        if img["id"] not in tracker["images"]:
            tracker["images"][img["id"]] = {
                "file": img["file"],
                "description": img["description"],
                "generated": False,
                "generated_at": None,
                "image_path": None
            }
    save_tracker(tracker)


def cmd_prompts():
    """Output ImageGen prompts for all pending images."""
    images = scan_all()
    tracker = load_tracker()
    generated = {k for k, v in tracker["images"].items() if v.get("generated")}

    pending = [img for img in images if img["id"] not in generated]
    if not pending:
        print("[INFO] All images are generated. No pending prompts.")
        return

    prompts = generate_prompts(pending)
    print(f"\n{'='*60}")
    print(f"  ImageGen Prompts ({len(prompts)} pending)")
    print(f"{'='*60}\n")

    for p in prompts:
        print(f"  ID: {p['id']}")
        print(f"  File: {p['file']}")
        print(f"  Prompt: {p['prompt']}")
        print(f"  Save as: zhihu_auto/images/{p['id']}.png")
        print()


def cmd_status():
    """Show image generation status."""
    tracker = load_tracker()
    images = tracker.get("images", {})

    if not images:
        print("[INFO] No images tracked. Run --scan first.")
        return

    generated = [v for v in images.values() if v.get("generated")]
    pending = [v for v in images.values() if not v.get("generated")]

    print(f"\n{'='*60}")
    print(f"  Image Status")
    print(f"{'='*60}")
    print(f"  Generated: {len(generated)}")
    print(f"  Pending: {len(pending)}")
    print()

    if generated:
        print("  [Generated]:")
        for img_id, info in sorted(images.items()):
            if info.get("generated"):
                print(f"    {img_id} -> {info.get('image_path', '?')}")
        print()

    if pending:
        print("  [Pending]:")
        for img_id, info in sorted(images.items()):
            if not info.get("generated"):
                print(f"    {img_id}: {info.get('description', '?')[:60]}")


def cmd_mark_done(img_id):
    """Mark an image as generated."""
    tracker = load_tracker()
    if img_id not in tracker["images"]:
        print(f"[ERROR] Image ID '{img_id}' not found. Run --scan first.")
        return

    img_path = IMAGES_DIR / f"{img_id}.png"
    if not img_path.exists():
        print(f"[WARN] Image file not found at {img_path}")
        print(f"[INFO] Marking as generated anyway...")

    tracker["images"][img_id]["generated"] = True
    tracker["images"][img_id]["generated_at"] = datetime.now().isoformat()
    tracker["images"][img_id]["image_path"] = str(img_path)
    save_tracker(tracker)
    print(f"[OK] Marked {img_id} as generated.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="知乎配图管理器")
    parser.add_argument("--scan", action="store_true", help="扫描所有内容配图占位符")
    parser.add_argument("--prompts", action="store_true", help="输出 ImageGen 提示词")
    parser.add_argument("--status", action="store_true", help="查看配图状态")
    parser.add_argument("--mark-done", type=str, metavar="ID", help="标记某图已生成")
    args = parser.parse_args()

    if args.scan:
        cmd_scan()
    elif args.prompts:
        cmd_prompts()
    elif args.mark_done:
        cmd_mark_done(args.mark_done)
    else:
        cmd_status()


if __name__ == "__main__":
    main()

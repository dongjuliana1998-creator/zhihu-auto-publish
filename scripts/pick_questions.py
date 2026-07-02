#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pick_questions.py — 从预建问题库按规则轮取每日问题

替代实时搜索（auto_find_questions.py），解决知乎反爬导致搜索结果不稳定的问题。

**优先级**：
  1. invited_questions.json（知乎邀请回答的问题）— 最高优先，真实问题，天然验证
  2. question_bank.json（预建问题库）— 备选

轮取规则（可配置）：
  - 每天取 3 个（或 --count 指定数量）
  - 7 天内不重复（同一问题 7 天内不再次使用）
  - priority=high 权重 3x，normal=1x（加权随机）
  - 自动排除回答数过少(<5)或过多(>200)的条目
  - 仅用 verified=true 的问题（如果 bank 里验证过的够用）

用法：
  python pick_questions.py                   # 从库中选 3 个，写入 candidate_questions.json
  python pick_questions.py --count 5         # 选 5 个
  python pick_questions.py --dry-run         # 模拟不写入
  python pick_questions.py --add-bank URL "标题" "角度"   # 手动添加问题到库
  python pick_questions.py --add-invited URL "标题"       # 手动添加邀请问题
  python pick_questions.py --verify URL      # 标记某问题为已验证
  python pick_questions.py --stats           # 查看库的使用统计
"""

import json
import random
import argparse
import sys
import io
from pathlib import Path
from datetime import datetime, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
BANK_FILE = ROOT / "question_bank.json"
INVITED_FILE = ROOT / "invited_questions.json"
OUTPUT_FILE = ROOT / "candidate_questions.json"
LOG_FILE = ROOT / "publish_log.json"

TODAY = datetime.now().strftime("%Y-%m-%d")


def load_invited() -> dict:
    """加载知乎邀请回答的问题"""
    if not INVITED_FILE.exists():
        return {"questions": []}
    try:
        with open(INVITED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"[WARN] invited_questions.json 读取失败: {e}")
        return {"questions": []}


def save_invited(data: dict):
    """保存邀请问题（更新状态）"""
    with open(INVITED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_valid_zhihu_question_url(url: str) -> bool:
    """检查 URL 是否为有效的知乎问题链接（包含数字ID）"""
    if not url or "zhihu.com/question" not in str(url):
        return False
    # 提取最后一段，要求是数字ID
    last_part = str(url).rstrip("/").split("/")[-1]
    return last_part.isdigit()


def pick_invited_questions(count: int, dry_run: bool = False) -> list:
    """从邀请问题中选取 pending 状态的问题"""
    data = load_invited()
    # 只选 pending 且 URL 有效的邀请问题（跳过占位符/TODO链接）
    pending = [q for q in data.get("questions", [])
               if q.get("status") == "pending" and is_valid_zhihu_question_url(q.get("url", ""))]

    if not pending:
        print("[INFO] 无待回答的邀请问题")
        return []

    selected = pending[:count]
    print(f"[INFO] 从邀请问题中选取 {len(selected)} 个（优先级高于问题库）")

    if not dry_run:
        # 标记为已选，避免下次重复使用
        for q in data["questions"]:
            if q in selected:
                q["status"] = "selected"
                q["selected_at"] = TODAY
        save_invited(data)

    return selected


def invited_to_candidate(invited: list) -> list:
    """将邀请问题转换为 candidate 格式"""
    candidates = []
    for q in invited:
        candidates.append({
            "title": q["title"],
            "url": q["url"],
            "topic": q.get("topic", ""),
            "angles": [q.get("notes", "")],
            "answers_est": 0,
            "priority": "high",
            "verified": True,  # 邀请问题天然真实
            "pillar": q.get("pillar", ""),
            "buyer_stage": q.get("buyer_stage", ""),
            "_source": "invited",
            "_inviter": q.get("source", ""),
        })
    return candidates


def add_invited(url: str, title: str):
    """手动添加邀请问题到 invited_questions.json"""
    data = load_invited()

    # 检查是否已存在
    existing = [q for q in data.get("questions", []) if q["url"] == url]
    if existing:
        print(f"[INFO] 邀请问题已存在，更新为 pending 状态")
        existing[0]["status"] = "pending"
        existing[0]["title"] = title
    else:
        new_q = {
            "url": url,
            "title": title,
            "source": "手动添加",
            "type": "manual",
            "received_at": TODAY,
            "status": "pending",
            "pillar": "",
            "buyer_stage": "",
            "notes": "",
        }
        data.setdefault("questions", []).append(new_q)
        print(f"[INFO] 已添加邀请问题: {title}")

    save_invited(data)


def load_bank() -> dict:
    if not BANK_FILE.exists():
        print(f"[ERROR] 问题库不存在: {BANK_FILE}")
        sys.exit(1)
    try:
        with open(BANK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] question_bank.json 损坏: {e}")
        try:
            bak = BANK_FILE.with_suffix(".json.bak")
            BANK_FILE.rename(bak)
            print(f"       已备份到 {bak.name}")
        except:
            pass
        sys.exit(1)


def save_bank(bank: dict):
    with open(BANK_FILE, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)


def is_recently_used(q: dict, days: int = 7) -> bool:
    """检查问题是否在最近 N 天内使用过"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return any(d >= cutoff for d in q.get("used_on", []))


def is_valid_answer_range(q: dict) -> bool:
    """检查回答数是否在合理范围(5-200)"""
    est = q.get("answers_est", 0)
    return 5 <= est <= 200


def pick_questions(bank: dict, count: int = 3, prefer_verified: bool = True) -> list:
    """从问题库中按规则选出 count 个问题"""
    rules = bank["_meta"]["pick_rules"]
    questions = bank["questions"]

    # 过滤掉尚未补充真实URL的占位问题
    questions = [q for q in questions if "PLACEHOLDER" not in q.get("url", "")]

    # 第一轮过滤：去掉最近 N 天用过的
    available = [q for q in questions if not is_recently_used(q, rules["avoid_repeat_days"])]

    # 第二轮过滤：回答数范围
    available = [q for q in available if is_valid_answer_range(q)]

    if len(available) < count:
        print(f"[WARN] 可用问题不足: {len(available)}/{count}")
        # 放宽限制：允许回答数范围外的也纳入
        available = [q for q in questions if not is_recently_used(q, rules["avoid_repeat_days"])]

    if prefer_verified:
        verified = [q for q in available if q.get("verified")]
        if len(verified) >= count:
            available = verified
            print(f"[INFO] 使用已验证问题: {len(verified)} 条")
        else:
            print(f"[WARN] 已验证问题不足 ({len(verified)}/{count})，无法选出足够问题")
            print(f"[WARN] 请运行 auto_find_questions.py 补充新问题，或手动验证现有问题")
            # 只返回已验证的，不足就发多少算多少
            available = verified
            count = min(count, len(verified))

    if len(available) < count:
        print(f"[WARN] 即使放宽限制也只有 {len(available)} 条")
        count = max(1, len(available))

    # 加权随机选择
    weights = []
    for q in available:
        w = rules["priority_weight"].get(q.get("priority", "normal"), 1)
        weights.append(w)

    # 按 topic 去重（尽量覆盖不同话题）
    selected = []
    used_topics = set()

    # 先加权随机选
    weighted_pool = list(zip(available, weights))
    random.shuffle(weighted_pool)

    # 优先选不同 topic
    for q, _ in sorted(weighted_pool, key=lambda x: -x[1]):  # 按权重降序
        if len(selected) >= count:
            break
        topic = q.get("topic", "")
        # 前 2 个优先选不同话题
        if len(selected) < 2 or topic not in used_topics or len(selected) >= count - 1:
            selected.append(q)
            used_topics.add(topic)

    # 如果还不够，从剩余中随机补
    if len(selected) < count:
        remaining = [q for q in available if q not in selected]
        random.shuffle(remaining)
        selected.extend(remaining[: count - len(selected)])

    return selected


def update_used_on(bank: dict, selected: list):
    """更新问题库中已选问题的 used_on"""
    selected_urls = {q["url"] for q in selected}
    for q in bank["questions"]:
        if q["url"] in selected_urls:
            if TODAY not in q.get("used_on", []):
                q.setdefault("used_on", []).append(TODAY)
    save_bank(bank)


def write_candidates(selected: list, source: str = "question_bank"):
    """写入 candidate_questions.json（兼容旧格式）"""
    candidates = []
    for q in selected:
        candidates.append({
            "title": q["title"],
            "url": q["url"],
            "topic": q.get("topic", ""),
            "angles": q.get("angles", []),
            "answers_est": q.get("answers_est", 0),
            "priority": q.get("priority", "normal"),
            "verified": q.get("verified", False),
            "pillar": q.get("pillar", ""),
            "buyer_stage": q.get("buyer_stage", ""),
        })

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "candidates": candidates,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] 已选择 {len(candidates)} 个问题 → {OUTPUT_FILE} (来源: {source})")


def add_to_bank(bank: dict, url: str, title: str, angles: str):
    """手动添加问题到库"""
    angle_list = [a.strip() for a in angles.split(";") if a.strip()]
    new_q = {
        "url": url,
        "title": title,
        "topic": "customer_followup",
        "answers_est": 0,
        "angles": angle_list,
        "priority": "normal",
        "verified": False,
        "used_on": [],
        "notes": "",
    }
    # 检查是否已存在
    existing = [q for q in bank["questions"] if q["url"] == url]
    if existing:
        print(f"[INFO] 问题已存在，更新信息")
        existing[0].update(new_q)
    else:
        bank["questions"].append(new_q)
        print(f"[INFO] 已添加: {title}")

    save_bank(bank)


def verify_question(bank: dict, url: str):
    """标记问题为已验证"""
    for q in bank["questions"]:
        if q["url"] == url:
            q["verified"] = True
            save_bank(bank)
            print(f"[OK] 已标记为已验证: {q['title']}")
            return
    print(f"[ERROR] 未找到: {url}")


def show_stats(bank: dict):
    """显示问题库统计"""
    questions = bank["questions"]
    total = len(questions)
    verified = sum(1 for q in questions if q.get("verified"))
    used_today = sum(1 for q in questions if TODAY in q.get("used_on", []))
    topics = {}
    for q in questions:
        t = q.get("topic", "unknown")
        topics[t] = topics.get(t, 0) + 1

    topic_names = {
        "customer_followup": "客户跟进",
        "whatsapp": "WhatsApp外贸",
        "team_management": "团队管理/客户资产",
        "customer_acquisition": "客户开发/获客",
        "sales_ops": "销售运营",
        "account_safety": "账号安全",
        "platform_choice": "平台选择",
        "tool_review": "工具测评与实操",
        "troubleshooting": "避坑与合规",
        "methodology": "另类思路/方法论",
        "industry_reality": "工业品实战",
        "supplier_sourcing": "采购与供应商",
        "team_building": "团队管理与成长",
        "market_intelligence": "行业趋势分析",
        "cross_border_tools": "跨境工具盘点",
        "payment_logistics": "收款与物流",
    }

    print(f"\n{'='*50}")
    print(f"  问题库统计")
    print(f"{'='*50}")
    print(f"  总条目:      {total}")
    print(f"  已验证:      {verified}/{total}")
    print(f"  今日已用:    {used_today}")
    print(f"\n  话题分布:")
    for t, count in sorted(topics.items(), key=lambda x: -x[1]):
        name = topic_names.get(t, t)
        print(f"    {name:<20} {count} 个")
    print(f"\n  最近使用:")
    recent = [q for q in questions if q.get("used_on")]
    recent.sort(key=lambda q: max(q["used_on"]), reverse=True)
    for q in recent[:5]:
        print(f"    {max(q['used_on'])} | {q['title'][:40]}")
    print()


def main():
    parser = argparse.ArgumentParser(description="从预建问题库轮取每日问题（优先使用知乎邀请问题）")
    parser.add_argument("--count", type=int, default=3, help="选取数量")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行，不写入")
    parser.add_argument("--add-bank", nargs=3, metavar=("URL", "TITLE", "ANGLES"),
                        help="添加问题到问题库（angles用分号分隔）")
    parser.add_argument("--add-invited", nargs=2, metavar=("URL", "TITLE"),
                        help="手动添加知乎邀请问题到 invited_questions.json")
    parser.add_argument("--verify", metavar="URL", help="标记问题为已验证")
    parser.add_argument("--stats", action="store_true", help="显示问题库统计")
    args = parser.parse_args()

    # --- 手动操作分支 ---
    if args.stats:
        bank = load_bank()
        show_stats(bank)
        # 也显示邀请问题统计
        inv_data = load_invited()
        pending = [q for q in inv_data.get("questions", []) if q.get("status") == "pending"]
        used = [q for q in inv_data.get("questions", []) if q.get("status") != "pending"]
        print(f"\n  邀请问题: {len(pending)} 个待回答, {len(used)} 个已处理")
        for q in pending:
            print(f"    ⏳ {q['title'][:50]} (来自: {q.get('source','?')})")
        return

    if args.verify:
        bank = load_bank()
        verify_question(bank, args.verify)
        return

    if args.add_bank:
        bank = load_bank()
        add_to_bank(bank, *args.add_bank)
        return

    if args.add_invited:
        add_invited(args.add_invited[0], args.add_invited[1])
        return

    # --- 核心流程：选问题（邀请问题优先）---
    print(f"\n{'='*60}")
    print(f"  轮取每日问题 (目标 {args.count} 个)")
    print(f"  日期: {TODAY}")
    print(f"{'='*60}\n")

    all_selected = []
    final_source = "question_bank"

    # 第一步：优先从邀请问题中选取
    remaining_count = args.count
    invited = pick_invited_questions(remaining_count, dry_run=args.dry_run)

    if invited:
        all_selected.extend(invited_to_candidate(invited))
        remaining_count -= len(invited)
        print(f"\n  邀请问题已选 {len(invited)} 个:")
        for i, q in enumerate(invited, 1):
            print(f"    {i}. {q['title'][:55]} (来自: {q.get('source','?')})")

    # 第二步：如果邀请问题不够，从问题库补充
    if remaining_count > 0:
        print(f"\n  还需 {remaining_count} 个，从问题库补充...")
        bank = load_bank()
        bank_selected = pick_questions(bank, count=remaining_count)
        all_selected.extend(bank_selected)

        if bank_selected:
            print(f"\n  问题库已选 {len(bank_selected)} 个:")
            for i, q in enumerate(bank_selected, 1):
                verified_mark = " [已验证]" if q.get("verified") else ""
                print(f"    {i}. {q['title'][:55]}{verified_mark}")
            if not args.dry_run:
                update_used_on(bank, bank_selected)

    # 确定来源标签
    if invited and len(all_selected) > len(invited):
        final_source = "mixed"
    elif invited:
        final_source = "invited"

    # 汇总输出
    print(f"\n{'─'*50}")
    print(f"  总共选中: {len(all_selected)} 个问题\n")

    for i, q in enumerate(all_selected, 1):
        src_tag = " [邀请]" if q.get("_source") == "invited" else ""
        verified_mark = " [已验证]" if q.get("verified") else ""
        print(f"  {i}. {q['title'][:58]}{src_tag}{verified_mark}")
        print(f"     {q['url']}")
        print()

    if not args.dry_run and all_selected:
        write_candidates(all_selected, source=final_source)
        print("[TIP] 自动化下一步将读取 candidate_questions.json 生成回答")
    elif not all_selected:
        print("[WARN] 无可用问题！请检查 invited_questions.json 或运行 auto_find_questions.py 补充问题库")
    else:
        print("[DRY RUN] 未写入文件")


if __name__ == "__main__":
    main()

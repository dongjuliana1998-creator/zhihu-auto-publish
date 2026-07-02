#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_find_questions.py v2 - 知乎热门问题自动发现、筛选与入库

核心改进（v2）：
  1. 修正 DOM 解析：知乎搜索结果卡片链接是回答 URL，需反推问题 URL
  2. 正确选择器：[class*=SearchResult-Card] 定位搜索卡片
  3. 自动去重：按 question ID 去重
  4. 自动入库：新发现的问题自动追加到 question_bank.json
  5. 关键词从 content_config.json 读取

用法：
  python auto_find_questions.py                         # 搜所有关键词，输出 Top N
  python auto_find_questions.py --keyword "WhatsApp 外贸" # 搜单个关键词
  python auto_find_questions.py --top 10                 # 返回前10个
  python auto_find_questions.py --json                   # JSON 格式输出
  python auto_find_questions.py --update-bank            # 自动更新 question_bank.json
  python auto_find_questions.py --exclude-answered       # 排除已回答的问题（默认开启）

输出文件:
  - candidate_questions.json: 当次搜索结果
  - question_bank.json: 问题库（--update-bank 时自动追加）
"""

import json
import sys
import io
import re
import time
import random
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
COOKIE_FILE = ROOT / "zhihu_cookies.json"
OUTPUT_FILE = ROOT / "candidate_questions.json"
QUESTION_BANK = ROOT / "question_bank.json"
CONTENT_CONFIG = ROOT / "content_config.json"
ANSWERED_LOG = ROOT / "answered_questions.json"
PUBLISH_LOG = ROOT / "publish_log.json"


def load_cookies(context) -> bool:
    """加载知乎登录 Cookie"""
    if not COOKIE_FILE.exists():
        print("  [WARN] 未找到 cookie 文件，可能需要重新登录")
        return False
    try:
        cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        context.add_cookies(cookies)
        print(f"  [OK] 已加载 {len(cookies)} 条 cookie")
        return True
    except Exception as e:
        print(f"  [ERROR] Cookie 加载失败: {e}")
        return False


def load_keywords() -> list:
    """从 content_config.json 读取搜索关键词，如果失败则用默认列表"""
    try:
        with open(CONTENT_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        keywords = cfg.get("search_keywords", [])
        if keywords:
            # 每天随机选 6-8 个关键词搜，避免每次都搜全部（太慢且容易被限制）
            daily_count = random.randint(6, min(8, len(keywords)))
            selected = random.sample(keywords, daily_count)
            print(f"  [KEYWORDS] 从 content_config.json 选取 {len(selected)} 个关键词")
            return selected
    except Exception as e:
        print(f"  [WARN] 读取 content_config.json 失败: {e}")

    # 默认回退关键词
    default_kw = [
        "WhatsApp 外贸",
        "WhatsApp 客户开发",
        "外贸 客户管理",
        "WhatsApp CRM",
        "外贸 获客",
        "WhatsApp 营销",
        "外贸 防飞单",
        "WhatsApp 多账号管理",
        "外贸 SOHO 工具",
        "外贸客户跟进",
        "LinkedIn 外贸获客",
        "海关数据 外贸",
        "外贸团队管理",
        "外贸找客户方法",
        "独立站 获客",
        "外贸工具 推荐",
    ]
    return default_kw


def load_question_bank() -> dict:
    """加载现有问题库"""
    if QUESTION_BANK.exists():
        try:
            with open(QUESTION_BANK, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"  [WARN] question_bank.json 损坏 ({e})，备份后重置")
            try:
                bak = QUESTION_BANK.with_suffix(".json.bak")
                QUESTION_BANK.rename(bak)
            except:
                pass
    return {"_meta": {"version": "0", "created": "", "description": ""}, "questions": []}


def save_question_bank(bank: dict):
    """保存问题库"""
    bank["_meta"]["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(QUESTION_BANK, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)


def load_answered_urls() -> set:
    """加载已发布过回答的问题 URL 集合"""
    urls = set()
    # 从 publish_log.json 获取已发布的
    try:
        if PUBLISH_LOG.exists():
            log_data = json.loads(PUBLISH_LOG.read_text(encoding="utf-8"))
            # answers/articles 以 dict 存储，遍历 values 提取 URL
            for section in ("answers", "articles"):
                section_data = log_data.get(section, {})
                if isinstance(section_data, dict):
                    for entry in section_data.values():
                        url = entry.get("url") or entry.get("question_url") or ""
                        if "/question/" in url:
                            qid_match = re.search(r"/question/(\d+)", url)
                            if qid_match:
                                urls.add(f"https://www.zhihu.com/question/{qid_match.group(1)}")
    except Exception:
        pass
    # 从 answered_questions.json 获取
    try:
        if ANSWERED_LOG.exists():
            data = json.load(ANSWERED_LOG)
            for u in data.get("answered_urls", []):
                if "/question/" in u:
                    urls.add(u.split("?")[0].split("#")[0])
    except Exception:
        pass
    return urls


def close_login_modal(page):
    """尝试关闭可能的登录弹窗"""
    selectors = [
        ".Modal-closeButton",
        "[class*=Modal] [class*=close]",
        "[class*=ModalCloseButton]",
        "button.Modal-closeIcon",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click()
                time.sleep(0.5)
                return True
        except Exception:
            continue
    return False


def extract_cards(page) -> list:
    """
    核心函数：从知乎搜索结果页面提取问题数据。

    关键发现（2026-06-29 验证）：
    - 搜索结果卡片的 CSS 类是 [class*=SearchResult-Card]
    - 卡片内的链接是回答 URL（/question/QID/answer/AID），不是纯问题 URL
    - 需要从回答 URL 反推问题 ID，构造问题 URL
    - 标题在卡片的 h2 或 [class*=Title] 元素中
    - 回答数在卡片文本的 "X 回答" 格式中
    """
    js_code = r"""() => {
        const cards = document.querySelectorAll("[class*='SearchResult-Card']");
        const results = [];

        for (const card of Array.from(cards)) {
            // 清理零宽空格
            const cardText = (card.textContent || "").replace(/\u200b/g, "").trim();

            // 在卡片中查找任何含 /question/ 的链接
            let qid = null;
            let rawHref = "";
            const links = Array.from(card.querySelectorAll("a"));
            for (const a of links) {
                let h = (a.getAttribute("href") || "");
                let match = h.match(/\/question\/(\d+)/);
                if (!match || match[1].length < 6) continue;  // question ID 至少 6 位
                // 排除 article URL（/question/xxxxx/article/yyyyy 格式）
                if (/\/article\/\d+/.test(h)) continue;
                qid = match[1];
                rawHref = h;
                break;
            }

            if (!qid || isNaN(parseInt(qid))) continue;

            // 提取标题
            const titleEl =
                card.querySelector("h2") ||
                card.querySelector("[class*='Title']") ||
                card.querySelector("[class*='title']");
            let title = titleEl ? (titleEl.textContent || "").replace(/\u200b/g, "").trim() : "";

            // 如果标题太短或为空，用卡片前80字符作为标题片段
            if (title.length < 5) {
                title = cardText.substring(0, 120);
            }

            // 提取回答数
            const ansMatch = cardText.match(/(\d+)\s*[个]?\s*回答/);
            const ansCount = ansMatch ? parseInt(ansMatch[1]) : 0;

            // 提取关注数
            const folMatch = cardText.match(/(\d+)\s*[个]?\s*关注/);
            const folCount = folMatch ? parseInt(folMatch[1]) : 0;

            if (title.length > 5) {
                results.push({
                    qid: qid,
                    qUrl: "https://www.zhihu.com/question/" + qid,
                    title: title.substring(0, 150),
                    answerCount: ansCount,
                    followerCount: folCount,
                });
            }
        }

        return results;
    }"""

    results = page.evaluate(js_code)
    return results


def question_score(answer_count: int, follower_count: int) -> float:
    """
    问题热度评分算法。
    - 回答太少 (<3): 可能太冷门
    - 回答太多 (>150): 竞品太多
    - 最佳区间: 5-50 个回答（有讨论但不过于拥挤）
    - 关注者越多越好
    """
    # 关注者基础分 (0-40)
    f_score = min(40, follower_count / 30)

    # 回答数得分 (0-60): 最佳区间 5-50
    if answer_count < 3:
        a_score = 10
    elif answer_count < 5:
        a_score = 25
    elif answer_count <= 15:
        a_score = 60   # 黄金区间
    elif answer_count <= 50:
        a_score = 55
    elif answer_count <= 100:
        a_score = 35
    elif answer_count <= 150:
        a_score = 18
    else:
        a_score = 8

    return f_score + a_score


def guess_pillar(title: str, keyword: str) -> str:
    """根据标题和关键词猜测内容支柱（粗略分类）"""
    t_lower = title.lower()
    kw_lower = keyword.lower()

    # 工具测评类
    tool_words = ["对比", "推荐", "哪个好", "怎么选", "工具", "软件", "crm", "测评", "横评"]
    if any(w in t_lower or w in kw_lower for w in tool_words):
        return "tool_review"

    # 避坑/合规类
    trouble_words = ["坑", "封号", "风险", "避", "注意", "违规", "合规", "防"]
    if any(w in t_lower for w in trouble_words):
        return "troubleshooting"

    # 方法论类
    method_words = ["方法论", "思路", "逻辑", "本质", "底层", "思维", "技巧"]
    if any(w in t_lower for w in method_words):
        return "methodology"

    # 行业观察类
    industry_words = ["行业", "趋势", "现状", "市场", "汽配", "机械", "工业"]
    if any(w in t_lower for w in industry_words):
        return "industry_reality"

    # 获客渠道类
    acquire_words = ["获客", "开发客户", "找客户", "引流", "渠道", "冷门"]
    if any(w in t_lower or w in kw_lower for w in acquire_words):
        return "customer_acquisition"

    # 团队管理类
    team_words = ["团队", "管理", "销售", "考核", "交接", "离职", "飞单"]
    if any(w in t_lower for w in team_words):
        return "team_building"

    # 默认
    return "tool_review"


def guess_buyer_stage(answer_count: int, title: str) -> str:
    """根据回答数量和标题猜测买家阶段"""
    t_lower = title.lower()
    
    # 大量回答 → 决策期或使用期（大家都在讨论具体方案）
    if answer_count > 30:
        return "consideration"
    
    # 方法论型 → 问题意识期
    method_words = ["为什么", "怎么", "如何", "什么", "是不是", "有没有"]
    if any(t_lower.startswith(w) for w in method_words):
        return "awareness"
    
    # 对比选择型 → 方案比选期
    compare_words = ["哪个好", "怎么选", "对比", "区别", "vs", "和"]
    if any(w in t_lower for w in compare_words):
        return "consideration"
    
    return "consideration"


def search_zhihu(page, keyword: str) -> list:
    """搜一个关键词，返回提取到的问题列表"""
    results = []
    search_url = f"https://www.zhihu.com/search?q={keyword}&type=content"

    print(f"  [SEARCH] \"{keyword}\"")
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
        time.sleep(random.uniform(2.5, 4))

        # 尝试关闭登录弹窗
        close_login_modal(page)

        # 滚动加载更多结果
        for _ in range(2):
            page.evaluate("window.scrollBy(0, 800)")
            time.sleep(random.uniform(0.6, 1.0))

        # 再滚一次确保底部加载
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)

        # 提取卡片数据
        raw_results = extract_cards(page)

        # 补充 keyword 和 score 信息
        for r in raw_results:
            score = question_score(r["answerCount"], r["followerCount"])
            results.append({
                "url": r["qUrl"],
                "title": r["title"],
                "keyword": keyword,
                "answer_count": r["answerCount"],
                "follower_count": r["followerCount"],
                "score": score,
                "pillar": guess_pillar(r["title"], keyword),
                "buyer_stage": guess_buyer_stage(r["answerCount"], r["title"]),
            })

        print(f"  [FOUND] {len(results)} 个问题")

    except Exception as e:
        print(f"  [ERROR] 搜索出错: {e}")

    return results


def main():
    parser = argparse.ArgumentParser(description="知乎热门问题自动发现 v2")
    parser.add_argument("--keyword", help="搜索关键词（可多次指定）", action="append")
    parser.add_argument("--top", type=int, default=10, help="返回前 N 个问题")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--update-bank", action=argparse.BooleanOptionalAction, default=True,
                        help="自动将新发现的问题追加到 question_bank.json（默认开启）")
    parser.add_argument("--exclude-answered", action=argparse.BooleanOptionalAction, default=True,
                        help="排除已回答的问题（默认开启）")
    parser.add_argument("--min-score", type=int, default=15, help="最低评分阈值")
    args = parser.parse_args()

    keywords = args.keyword if args.keyword else load_keywords()

    # 加载已回答的问题 URL
    answered_urls = set()
    if args.exclude_answered:
        answered_urls = load_answered_urls()

    print(f"\n{'=' * 65}")
    print(f"  ZHIHU AUTO QUESTION DISCOVERY v2")
    print(f"  Keywords ({len(keywords)}): {', '.join(keywords[:5])}{'...' if len(keywords) > 5 else ''}")
    print(f"  Excluded (already answered): {len(answered_urls)}")
    print(f"  Update question_bank: {'YES' if args.update_bank else 'NO'}")
    print(f"{'=' * 65}\n")

    all_questions = []

    # ── 浏览器阶段 ──
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            slow_mo=20,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
            )
            load_cookies(context)
            page = context.new_page()

            for kw in keywords:
                results = search_zhihu(page, kw)
                all_questions.extend(results)
                # 搜索间隔，避免触发频率限制
                time.sleep(random.uniform(1.5, 3))
        finally:
            browser.close()

    # ── 去重（按 QID） ──
    print(f"\n[RAW] Total: {len(all_questions)} results")

    seen_qids = {}
    for q in all_questions:
        qid = q["url"].rstrip("/").split("/")[-1]

        if qid in seen_qids:
            # 保留 score 更高的那个
            if q["score"] > seen_qids[qid]["score"]:
                seen_qids[qid] = q
        else:
            # 排除已回答的
            if args.exclude_answered:
                is_answered = any(
                    q["url"] == u or q["url"].startswith(u.rstrip("/")) or u.startswith(q["url"])
                    for u in answered_urls
                )
                if is_answered:
                    continue

            # 排除评分太低的
            if q["score"] < args.min_score:
                continue

            seen_qids[qid] = q

    # 按 score 排序
    sorted_qs = sorted(seen_qids.values(), key=lambda x: x["score"], reverse=True)
    top_n = sorted_qs[:args.top]

    print(f"[FILTERED] After dedup+filter: {len(seen_qids)}, Top-{args.top}: {len(top_n)}\n")

    # ── 输出结果表 ──
    print(f"{'-' * 75}")
    print(f"{'#':<4} {'Score':<7} {'Answers':<9} {'Followers':<10} {'Title'}")
    print(f"{'-' * 75}")
    for i, q in enumerate(top_n, 1):
        title_display = q["title"][:45].replace("\n", " ").strip()
        print(f"{i:<4} {q['score']:<7.1f} {q['answer_count']:<9} {q['follower_count']:<10} {title_display}")
        print(f"     {q['url']}")
    print(f"{'-' * 75}")

    # ── 保存候选结果 ──
    output_data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "keywords_used": keywords,
        "total_found": len(all_questions),
        "after_filter": len(seen_qids),
        "candidates": top_n,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # ── 自动入库到 question_bank.json ──
    new_added = 0
    if args.update_bank:
        bank = load_question_bank()
        existing_urls = set(q.get("url", "") for q in bank.get("questions", []))
        existing_qids = set(q.get("url", "").rstrip("/").split("/")[-1]
                           for q in bank.get("questions", []))

        for q in top_n:
            qid = q["url"].rstrip("/").split("/")[-1]

            # 检查是否已在库中
            if q["url"] in existing_urls or qid in existing_qids:
                continue

            # 构造新条目
            new_entry = {
                "title": q["title"],
                "url": q["url"],
                "topic": q.get("pillar", ""),
                "priority": "normal",
                "verified": False,
                "angles": [
                    f"{q['title']} — 从{q.get('keyword', '')}角度切入",
                    f"实操经验分享角度",
                ],
                "answers_est": max(0, q.get("answer_count", 0)),
                "pillar": q.get("pillar", "tool_review"),
                "buyer_stage": q.get("buyer_stage", "consideration"),
                "used_on": [],
                "_discovered_at": datetime.now().strftime("%Y-%m-%d"),
            }

            bank["questions"].append(new_entry)
            new_added += 1

        if new_added > 0:
            save_question_bank(bank)
            print(f"\n[BANK UPDATE] +{new_added} new questions added to question_bank.json")
            print(f"              Bank total: {len(bank['questions'])} questions")
        else:
            print(f"\n[BANK] No new questions to add (all already in bank)")

    print(f"\n[DONE] Results saved to: {OUTPUT_FILE}")
    if args.update_bank:
        print(f"[BANK] Question bank updated at: {QUESTION_BANK}")
    print(f"\nNext step: run pick_questions.py to select today's questions")


if __name__ == "__main__":
    main()

# WADesk 知乎自动运营系统 — 工作流文档

> **版本**: v7 分时段版 | **更新**: 2026-06-29
> **适用产品**: WADesk (https://wadesk.io/cn) — WhatsApp 多账号客户管理CRM
> **定位**: 为外贸出海团队提供一站式知乎内容自动运营能力，可复用、可迁移。

---

## 一、项目概述

### 1.1 目标

每天自动完成 **3 篇知乎文章 + 3 条知乎回答** 的生产和发布，全流程自动化。

### 1.2 核心策略

- **流量导向**: 知乎高流量内容型 = 盘点对比、实操教程、避坑清单、冷门方法论
- **80/20 植入**: 前 80% 纯干货，后 20% 自然带出 WADesk
- **分时段发布**: 避免一次性 6 篇触发平台风控，拆成 09:00 / 12:00 / 13:00 三批
- **10 大内容支柱**: 覆盖工具测评、获客渠道、避坑、方法论、行业观察、采购、团队管理、市场趋势、跨境工具、收付款物流

### 1.3 已发布验证

| 类型 | 已验证链接 |
|------|-----------|
| 文章+双图 | https://zhuanlan.zhihu.com/p/2055047873885114881 |
| 文章 | https://zhuanlan.zhihu.com/p/2054882584824492724 |
| 回答+配图 | https://www.zhihu.com/question/555079740/answer/2054943351036711639 |

---

## 二、系统架构

### 2.1 文件结构总览

```
zhihu_auto/
├── 📄 核心脚本 (6个)
│   ├── daily_publish_v2.py       ← 统一调度器（入口）
│   ├── publish_article_v4.py     ← 文章发布 + 配图上传
│   ├── publish_answer_v11.py     ← 回答发布 + 配图上传
│   ├── pick_questions.py         ← 问题轮取
│   ├── auto_find_questions.py    ← 搜索入库
│   └── zhihu_auth.py            ← 扫码/Cookie 登录
│
├── 📊 配置与数据 (6个)
│   ├── content_config.json       ← 内容策略核心配置（77关键词/10支柱/标题公式）
│   ├── question_bank.json       ← 问题库（59+条，覆盖10支柱）
│   ├── zhihu_config.json        ← 知乎站点配置
│   ├── zhihu_cookies.json       ← 登录态 Cookie
│   ├── publish_log.json         ← 发布记录（防重复）
│   └── candidate_questions.json ← 当日候选问题（临时）
│
├── 🛠 工具 (2个)
│   ├── manage_images.py         ← 配图管理（扫描/提示词/追踪）
│   └── image_tracker.json       ← 配图状态追踪
│
├── 📝 内容文件 (6个)
│   ├── articles/
│   │   ├── article_1.txt        ← 文章（第一行=标题）
│   │   ├── article_2.txt
│   │   └── article_3.txt
│   └── answers/
│       ├── answer_1.txt         ← 回答（第一行=问题URL）
│       ├── answer_2.txt
│       └── answer_3.txt
│
├── 🖼 配图 (9张)
│   └── images/
│       ├── article_1_img1.png, article_1_img2.png
│       ├── article_2_img1.png, article_2_img2.png
│       ├── article_3_img1.png, article_3_img2.png
│       ├── answer_1_img1.png, answer_2_img1.png, answer_3_img1.png
│
└── 📚 知识库 (6个)
    ├── PRODUCT_KNOWLEDGE.md     ← 产品知识、功能→利益→结果转化表
    ├── CONTENT_GUIDE.md         ← 内容写作规范
    ├── WORKFLOW.md              ← 本文件
    ├── README.md
    └── MEMORY.md                ← 项目运维记录
```

### 2.2 脚本调用关系

```
daily_publish_v2.py (调度器)
├── pick_questions.py          ──→ 从 question_bank.json 选问题
├── AI 内容生成 (WorkBuddy)     ──→ answer_1~3.txt + article_1~3.txt
├── manage_images.py --scan    ──→ 扫描配图占位符
├── ImageGen (WorkBuddy)       ──→ 生成 9 张配图
├── publish_article_v4.py      ──→ 发布文章（Playwright 浏览器自动化）
└── publish_answer_v11.py      ──→ 发布回答（Playwright 浏览器自动化）
```

### 2.3 数据流向

```
content_config.json (策略)
        ↓ 驱动
question_bank.json (问题池)
        ↓ pick_questions.py
candidate_questions.json (当日3题)
        ↓ AI 生成
article_1~3.txt + answer_1~3.txt (内容)
        ↓ manage_images.py 扫描 + ImageGen 生成
images/*.png (配图)
        ↓ daily_publish_v2.py 分批调度
publish_article_v4.py + publish_answer_v11.py (浏览器自动化)
        ↓
知乎专栏 / 知乎回答 (公开发布)
        ↓ 记录
publish_log.json (防重复发布)
```

---

## 三、完整工作流（6步）

### 3.1 每日时间线

| 时间 | 批次 | 动作 |
|------|------|------|
| **09:00** | Batch 1 | Step 0~4 全部执行 + 发布第 1 批（1 文 + 1 答） |
| **12:00** | Batch 2 | 仅发布第 2 批（1 文 + 1 答） |
| **13:00** | Batch 3 | 仅发布第 3 批（1 文 + 1 答） |

### 3.2 Step 0 — 搜题入库

**脚本**: `auto_find_questions.py`

**做什么**: 从 `content_config.json` 的 77 个搜索关键词中随机选 6-8 个，Playwright 打开知乎搜索 → 解析搜索结果卡片 → 提取问题标题/URL/回答数/关注数 → 打分排序 → 新问题自动追加到 `question_bank.json`。

**核心算法**: 问题热度 = 关注者分(0-40) + 回答数分(0-60)，黄金区间为 5-50 个回答。

**命令**:
```bash
python auto_find_questions.py --top 15              # 自动搜索入库
python auto_find_questions.py --keyword "WhatsApp 外贸" --top 10  # 搜指定话题
```

**前置条件**: `zhihu_cookies.json` 有效（否则跳过搜题，仍可从问题库轮取）。

### 3.3 Step 1 — 轮取问题

**脚本**: `pick_questions.py`

**选题规则**:
1. 7 天内不重复同一问题
2. 仅用 `verified=true` 的问题（已人工确认可作答）
3. 回答数 5-200 区间（太冷/太热都跳过）
4. 优先覆盖不同话题（前 2 题强制不同 pillar）
5. `priority=high` 权重 3x，`normal` 权重 1x

**命令**:
```bash
python pick_questions.py --count 3          # 选 3 题 → candidate_questions.json
python pick_questions.py --stats            # 问题库统计
python pick_questions.py --verify URL       # 标记问题为已验证
```

### 3.4 Step 2 — AI 生成内容

**执行者**: WorkBuddy AI（自动化 prompt 驱动）

**输入**: `candidate_questions.json` 中的 3 个问题 + `content_config.json` 中的内容策略

**输出**:
- `articles/article_1.txt`, `article_2.txt`, `article_3.txt`（2200-3500字）
- `answers/answer_1.txt`, `answer_2.txt`, `answer_3.txt`（800-1500字）

**内容文件格式规范**:
```
文章文件格式:             回答文件格式:
第一行: 标题              第一行: 问题 URL
空行                      空行
正文                      正文
【配图1: 描述】           【配图1: 描述】
【配图2: 描述】
```

**内容创作规则**（详细见 `content_config.json`）:
- 标题从 7 种文章公式 / 5 种回答公式中选择
- 正文中 `【配图 N：描述】` 占位符，发布时自动替换为实际图片
- 禁止: Markdown 表格、虚构数据、"不是...而是..."句式、"标品/非标品"
- 每篇 ≥1-2 处 Loss Aversion 表达 + ≥1 处 Social Proof 表达
- WADesk 植入使用 Feature→Benefit→Outcome 转化链（不写功能名）

### 3.5 Step 3 — 配图扫描

**脚本**: `manage_images.py`

**做什么**: 扫描 articles/ 和 answers/ 中的所有 `【配图 N：描述】` 占位符 → 生成 ImageGen 提示词 → 更新 `image_tracker.json` 追踪状态。

**命令**:
```bash
python manage_images.py --scan       # 扫描所有占位符
python manage_images.py --prompts    # 输出待生成图片的 ImageGen 提示词
python manage_images.py --status     # 查看配图生成状态
```

### 3.6 Step 4 — 生成配图

**执行者**: ImageGen（WorkBuddy 内置工具）

**规格**: 回答 1 张 + 文章 2 张 × 3 = **9 张/天**

**命名规则**:
```
answer_1.txt  → images/answer_1_img1.png
article_1.txt → images/article_1_img1.png, article_1_img2.png
```

配图生成完成后更新 `image_tracker.json` 中的 `generated: true`。

### 3.7 Step 5 — 分时段发布

**脚本**: `daily_publish_v2.py`

**核心机制**: 
- 读取 `publish_log.json` 跳过已发布内容（`--force` 可强制覆盖）
- 自动从 `images/` 匹配配图（按文件名前缀匹配）
- 调用 `publish_article_v4.py` 和 `publish_answer_v11.py`（Playwright 浏览器自动化）
- 文章间间隔 45-90 秒，回答间间隔 90-150 秒（模拟人工）
- 配图未就绪时自动退化为纯文本发布

**命令**:
```bash
python daily_publish_v2.py                                    # 发布所有待发布内容
python daily_publish_v2.py --max-articles 1 --max-answers 1   # 分批：只发1文+1答
python daily_publish_v2.py --articles-only                    # 仅文章
python daily_publish_v2.py --answers-only                     # 仅回答
python daily_publish_v2.py --force                            # 忽略已发布标记
python daily_publish_v2.py --dry-run                          # 干跑（不实际发布）
python daily_publish_v2.py --stats                            # 查看发布统计
```

**单篇发布**（调试用）:
```bash
PYTHONIOENCODING=utf-8 python publish_article_v4.py --file article.txt --images img1.png,img2.png
PYTHONIOENCODING=utf-8 python publish_answer_v11.py --q https://www.zhihu.com/question/xxx --file answer.txt --image img.png
```

---

## 四、核心技术实现

### 4.1 浏览器自动化（Playwright）

两个发布脚本都基于 Playwright 控制 Chromium 浏览器：

| 组件 | 文章 (v4) | 回答 (v11) |
|------|-----------|------------|
| 目标页面 | `zhuanlan.zhihu.com/write` | `www.zhihu.com/question/{QID}` |
| 编辑器 | Draft.js（知乎自研） | Draft.js |
| 输入方式 | `keyboard.type()` 逐字输入 | `keyboard.type()` 逐字输入 |
| 配图上传 | 点击 `button[aria-label='图片']` → `set_input_files` → 等待 `<img>` 出现 | 同左 |
| 发布按钮 | `button:has-text("发布")`（含 `\u200b` 零宽空格处理） | `button:has-text("发布回答")`（含 `\u200b`） |

### 4.2 配图占位符处理

```python
# 正则（兼容空格）
IMAGE_PLACEHOLDER_RE = re.compile(r'【配图\s*(\d+)[:：]\s*(.+?)】')

# 处理逻辑
# 有配图 → 替换占位符为实际图片元素
# 无配图 → 自动删除占位符文本，不发垃圾内容到知乎
```

### 4.3 发布记录格式

`publish_log.json` 结构：
```json
{
  "articles": {
    "article_1.txt": {
      "url": "https://zhuanlan.zhihu.com/p/xxx",
      "title": "文章标题",
      "published_at": "2026-06-29 11:29:42"
    }
  },
  "answers": {
    "answer_2.txt": {
      "url": "https://www.zhihu.com/question/xxx/answer/xxx",
      "title": "问题标题",
      "published_at": "2026-06-29 15:04:24"
    }
  },
  "last_run": "2026-06-29 23:23:36"
}
```

### 4.4 反风控措施

| 措施 | 参数 |
|------|------|
| 字符间延迟 | 5-12ms（模拟打字） |
| 输入后停顿 | 3-6 秒（模拟人工审查） |
| 文章间间隔 | 45-90 秒随机 |
| 回答间间隔 | 90-150 秒随机 |
| 分时段发布 | 08:00 / 12:00 / 13:00 |
| User-Agent | 真实 Chrome 126 UA |
| 浏览器启动 | `--disable-blink-features=AutomationControlled` |

---

## 五、内容策略速查

### 5.1 10 大内容支柱

| 简称 | 名称 | 周最低篇数 | 核心关键词 |
|------|------|-----------|-----------|
| `tool_review` | WhatsApp 工具测评 | 1 | CRM选型、多账号管理、工具对比 |
| `customer_acquisition` | 获客渠道盘点 | 1 | 找客户、B2B平台、海关数据、冷门方法 |
| `troubleshooting` | 避坑与合规 | 1 | 封号、踩坑、账号安全 |
| `methodology` | 另类思路/方法论 | 1 | 底层逻辑、认知框架、客户管理 |
| `industry_reality` | 工业品实战 | 1 | 汽配、机械、B2B、长周期 |
| `supplier_sourcing` | 采购与供应商 | 0 | 验厂、1688、谈判、采购渠道 |
| `team_building` | 团队管理 | 0 | 飞单、销售考核、SOP、交接 |
| `market_intelligence` | 行业趋势 | 0 | 出口数据、RCEP、东南亚 |
| `cross_border_tools` | 跨境工具盘点 | 0 | AI工具、Chrome插件、邮件追踪 |
| `payment_logistics` | 收款与物流 | 0 | T/T、信用证、清关、国际快递 |

### 5.2 标题公式速查

**回答**（5 种）: 翻问题型 / 经验总结型 / 后果警告型 / 颠覆常识型 / 简单方案型

**文章**（7 种）: 结论前置型 / 盘点对比型 / 实操教程型 / 避坑清单型 / 冷门方法论型 / 场景切入型 / 行业洞察型

### 5.3 WADesk 植入规范

核心原则：**不写功能名，写「用了之后什么样」**

```
功能: 多账号聚合管理
错误: "WADesk 支持多账号聚合管理"
正确: "不用反复切换账号，一个界面看所有客户消息。销售从'今天聊了哪几个号'
       变成'今天聊了哪几个客户'，不再漏消息。"
```

### 5.4 硬性禁止

- Markdown 表格
- 虚构具体数字
- "标品""非标品"
- "不是……而是……"句式
- "随着全球化深入……"等 AI 模板开头
- 正文出现内部分类标注（content_type/pillar/buyer_stage）

---

## 六、自动化配置

### 6.1 WorkBuddy 自动化（3个）

| 批次 | 时间 | ID | 动作 |
|------|------|----|------|
| Batch 1 | 每天 09:00 | `automation-1782698548004` | Step 0~4 全流程 + 发布第1批 |
| Batch 2 | 每天 12:00 | `automation-1782746599849` | 仅 `--max-articles 1 --max-answers 1` |
| Batch 3 | 每天 13:00 | `automation-1782746607618` | 仅 `--max-articles 1 --max-answers 1` |

### 6.2 自动化 Prompt 要点

Batch 1 的 prompt 需涵盖完整的 6 步流程，确保：
1. 先执行 `auto_find_questions.py --top 15`（Cookie过期时跳过并警告）
2. 再执行 `pick_questions.py --count 3`
3. 读取选出的 3 个问题 + `content_config.json` → AI 生成 3 篇回答 + 3 篇文章
4. `manage_images.py --scan` → 输出 ImageGen 提示词 → 生成 9 张配图
5. `daily_publish_v2.py --max-articles 1 --max-answers 1` 发第 1 批

---

## 七、快速上手（复用指南）

### 7.1 环境准备

```bash
# 依赖
pip install playwright
playwright install chromium

# Python 3.10+
# WorkBuddy 环境（用于自动化调度和 ImageGen）
```

### 7.2 首次配置

1. **获取知乎 Cookie**:
   ```bash
   python zhihu_auth.py
   ```
   扫码登录后自动保存 `zhihu_cookies.json`

2. **修改内容策略**（如需自定义）:
   编辑 `content_config.json`:
   - `search_keywords`: 搜索关键词列表
   - `content_pillars`: 内容支柱定义
   - `article_titles`: 预置标题库

3. **修改产品知识**（如迁移到其他产品）:
   编辑 `PRODUCT_KNOWLEDGE.md` 中的产品信息、功能列表、Feature→Benefit→Outcome 转化链

4. **验证流程**:
   ```bash
   # 干跑测试（不实际发布）
   python daily_publish_v2.py --dry-run

   # 发布单篇测试
   PYTHONIOENCODING=utf-8 python publish_article_v4.py --file articles/test.txt --dry-run
   ```

### 7.3 迁移到其他产品/品牌

更换以下内容即可复用框架：

| 需要改的 | 文件 | 说明 |
|----------|------|------|
| 目标网址 | `publish_article_v4.py`, `publish_answer_v11.py` | Playwright 选择器和页面 URL |
| 产品信息 | `PRODUCT_KNOWLEDGE.md` | 功能列表、转化链、使用场景 |
| 搜索关键词 | `content_config.json` → `search_keywords` | 目标话题的关键词 |
| 内容支柱 | `content_config.json` → `content_pillars` | 你的产品能写什么话题 |
| 标题库 | `content_config.json` → `article_titles` | 预生成标题 |
| 配图风格 | `manage_images.py` → `_build_image_prompt()` | ImageGen 提示词模板 |

**框架可复用部分**:
- `pick_questions.py` — 问题库轮取逻辑（通用，只依赖 question_bank.json）
- `auto_find_questions.py` — 知乎搜索 + 自动入库（站点特定，需根据目标平台改写）
- `daily_publish_v2.py` — 调度器框架（通用）
- `manage_images.py` — 配图管理框架（通用）
- `publish_article_v4.py` / `publish_answer_v11.py` — 发布器（站点特定，需重写选择器）

### 7.4 日常运维

```bash
# 查看问题库健康度
python pick_questions.py --stats

# 查看发布记录
python daily_publish_v2.py --stats

# 手动搜题补充问题库
python auto_find_questions.py --top 15

# 配图状态检查
python manage_images.py --status

# 强制重新发布某篇（覆盖已发布标记）
python daily_publish_v2.py --force --max-articles 1 --max-answers 0
```

---

## 八、故障排查

### Cookie 过期

**现象**: 发布时报 Cookie 错误，自动化跳过搜题步骤

**处理**: 
```bash
python zhihu_auth.py      # 重新扫码登录
```

### 配图未显示

**现象**: 文章发布后显示 `【配图1：...】` 文字而非图片

**排查**:
```bash
python manage_images.py --scan    # 检查占位符
python manage_images.py --status  # 检查图片是否已生成
ls images/                        # 确认图片文件存在且命名正确
```

**常见原因**：
1. 配图未生成 → 运行 ImageGen
2. 正则不匹配 → `【配图 1：...】` 和 `【配图1：...】` 空格差异（已修复，兼容两种格式）

### 发布失败

**查看错误日志**:
```bash
python daily_publish_v2.py --dry-run --max-articles 1 --max-answers 1
```

**常见原因**:
- 知乎页面结构变更 → 检查 Playwright 选择器
- 网络问题 → 重试
- 编辑器未加载完成 → 等待时间不足，增加延迟
- Cookie 过期 → 重新登录

### 内容被跳过不发布

**原因**: `publish_log.json` 已记录该文件为"已发布"

**处理**:
```bash
# 方法1: 使用 --force 强制发布
python daily_publish_v2.py --force

# 方法2: 手动编辑 publish_log.json 删除对应条目
```

---

## 九、版本演进

| 版本 | 日期 | 关键变化 |
|------|------|---------|
| v1 | 2026-06-25 | 初始版本，纯文本发布 |
| v2 | 2026-06-26 | 配图上传支持，ContentConfig v3 |
| v3 | 2026-06-27 | 内容支柱从 4 → 5 个 |
| v4 | 2026-06-28 | 配图双图端到端验证，v4+v11 发布器 |
| v5 | 2026-06-28 | 支柱 5 → 10，覆盖外贸全场景 |
| v6 | 2026-06-29 | 自动搜题入库，全流程自动化 |
| v7 | 2026-06-29 | **当前版本**: 分时段发布，代码清理，14 处修复 |

---

> **维护**: WADesk 运营团队 | **自动化平台**: WorkBuddy | **内容平台**: 知乎

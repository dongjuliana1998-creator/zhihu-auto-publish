# WADesk 知乎自动运营系统

> 每天自动在知乎发布 3 条回答 + 3 篇文章，为 WADesk（https://wadesk.io/cn）做内容营销。

---

## 目录

1. [项目简介](#项目简介)
2. [系统架构](#系统架构)
3. [文件结构](#文件结构)
4. [安装配置](#安装配置)
5. [日常运行](#日常运行)
6. [邀请回答自动抓取](#邀请回答自动抓取)
7. [内容规则](#内容规则)
8. [常见问题](#常见问题)

---

## 项目简介

### 一句话

**每天自动在知乎发布 3 条回答 + 3 篇文章**，为 WADesk（WhatsApp 多账号客户管理系统）做内容营销。

### 发布节奏

每天分 3 批自动发布（通过 WorkBuddy 自动化任务触发）：

| 批次 | 时间 | 内容 |
|------|------|------|
| Batch 1 | 09:30 | 1 篇文章 + 1 条回答 |
| Batch 2 | 12:00 | 1 篇文章 + 1 条回答 |
| Batch 3 | 13:30 | 1 篇文章 + 1 条回答 |

### 内容规格

| 类型 | 字数 | 配图 | 说明 |
|------|------|------|------|
| 回答 | 300-800 字 | 无 | 不配图，避免触发知乎 AI 检测 |
| 文章 | 2200-3500 字 | 2 张 | 配图通过 Playwright 自动上传 |

### 选题机制

1. **优先**：知乎「邀请回答」通知里的问题（通过 API 自动抓取）
2. **补充**：`question_bank.json` 里的问题池（手动添加或邀请溢出）

每天发布前自动刷新邀请回答数据，确保用最新的邀请。

---

## 系统架构

```
每日流程：
                                                                  
  09:30                        12:00               13:30         
  ──────────────────────────────────────────────────────────── 
  Batch 1                      Batch 2            Batch 3      
     │                            │                  │          
     ▼                            ▼                  ▼          
  ┌─────────────────────┐   ┌─────────┐       ┌─────────┐    
  │ fetch_invited_      │   │ 发布     │       │ 发布     │    
  │ questions.py        │   │ article_2 │       │ article_3 │    
  │ (抓取最新邀请回答)   │   │ answer_2  │       │ answer_3  │    
  └─────────────────────┘   └─────────┘       └─────────┘    
            │                                                      
            ▼                                                      
  ┌─────────────────────┐                                          
  │ pick_questions.py   │                                          
  │ (选 1 个问题)        │                                          
  └─────────────────────┘                                          
            │                                                      
            ▼                                                      
  ┌─────────────────────┐                                          
  │ 生成 article_1.txt  │                                          
  │ 生成 answer_1.txt   │                                          
  │ 生成配图 (ImageGen)  │                                          
  └─────────────────────┘                                          
            │                                                      
            ▼                                                      
  ┌─────────────────────┐                                          
  │ daily_publish_v2.py │                                          
  │ (发布 article_1 +   │                                          
  │  answer_1)           │                                          
  └─────────────────────┘                                          
```

---

## 文件结构

```
zhihu_auto/
│
├── README.md                       ← 本文件
├── CONTENT_GUIDE.md                ← 内容生成规则（AI 提示词模板）
├── PRODUCT_KNOWLEDGE.md            ← 产品知识库（WADesk 功能、用户画像、写作风格）
│
├── scripts/                        ← 发布脚本（不需要改）
│   ├── fetch_invited_questions.py  ← 抓取知乎邀请回答（API 方式，无需浏览器）
│   ├── pick_questions.py           ← 选题：从邀请问题 + 问题池选每日问题
│   ├── daily_publish_v2.py         ← 一键发布调度器（自动调用 fetch + 发布）
│   ├── publish_article_v4.py       ← 发布单篇文章（支持配图自动上传）
│   ├── publish_answer_v11.py       ← 发布单条回答（不配图，避免 AI 检测）
│   ├── zhihu_publish_common.py     ← 发布公共模块（浏览器复用、Cookie 刷新）
│   ├── zhihu_auth.py               ← 知乎扫码登录 & Cookie 管理
│   └── manage_images.py            ← 配图状态追踪
│
├── config/                         ← 配置文件（可能需要改）
│   ├── zhihu_config.json           ← 知乎账号配置、发布规则
│   ├── content_config.json         ← 搜索关键词、内容规格
│   ├── invited_questions.json      ← 邀请回答库（自动更新）
│   └── question_bank.json          ← 问题池（手动维护）
│
├── knowledge/                      ← 知识库（AI 生成内容时读取）
│   ├── PRODUCT_KNOWLEDGE.md        ← 产品知识
│   └── USER_PERSONA.md             ← 用户画像（5 类目标客户）
│
├── articles/                       ← 生成的文章（自动生成）
├── answers/                        ← 生成的回答（自动生成）
├── images/                         ← 生成的配图（自动生成）
│
└── 运行时文件（自动生成）
    ├── zhihu_cookies.json          ← 知乎登录态（7 天有效期）
    ├── publish_log.json             ← 已发布记录（防重复发布）
    └── image_tracker.json           ← 配图状态追踪
```

---

## 安装配置

### 1. 安装 WorkBuddy

从 https://www.codebuddy.cn 下载安装。

### 2. 安装 Python 依赖

```cmd
pip install playwright
playwright install chromium
```

### 3. 知乎扫码登录

```cmd
cd zhihu_auto
python scripts/zhihu_auth.py
```

脚本会打开浏览器，用知乎 App 扫码登录。登录成功后 Cookie 自动保存到 `zhihu_cookies.json`（7 天有效）。

### 4. 设置自动化任务

在 WorkBuddy 对话里说：

> 帮我创建 3 个自动化任务：
> 1. 每天 09:30 运行 `daily_publish_v2.py`
> 2. 每天 12:00 运行 `daily_publish_v2.py --max-articles 1 --max-answers 1`
> 3. 每天 13:30 运行 `daily_publish_v2.py --max-articles 1 --max-answers 1`

---

## 日常运行

### 一键发布所有（最常用）

```cmd
cd zhihu_auto
python scripts\daily_publish_v2.py
```

### 分批次发布

```cmd
# Batch 1 (09:30)
python scripts\daily_publish_v2.py --max-articles 1 --max-answers 1

# Batch 2 (12:00)
python scripts\daily_publish_v2.py --max-articles 1 --max-answers 1

# Batch 3 (13:30)
python scripts\daily_publish_v2.py --max-articles 1 --max-answers 1
```

### 只发文章 / 只发回答

```cmd
python scripts\daily_publish_v2.py --articles-only
python scripts\daily_publish_v2.py --answers-only
```

### 先看看不发（干跑）

```cmd
python scripts\daily_publish_v2.py --dry-run
```

### 强制重发（跳过已发布检查）

```cmd
python scripts\daily_publish_v2.py --force
```

---

## 邀请回答自动抓取

### 功能说明

脚本 `fetch_invited_questions.py` 通过知乎 API 自动抓取「邀请回答」通知：

- **API 方式**：直接用 HTTP + Cookie 调知乎 API（默认，快速）
- **浏览器方式**：`--use-browser` 参数（知乎加了反爬时兜底）
- **自动去重**：按问题 ID 去重，不会重复入库
- **自动溢出**：邀请数 > 3 条时，多余的自动补进 `question_bank.json`

### 手动运行

```cmd
# 抓 5 页（约 100 条邀请）
python scripts\fetch_invited_questions.py --max-pages 5

# 试运行（不写入文件）
python scripts\fetch_invited_questions.py --dry-run

# 用浏览器方式（兜底）
python scripts\fetch_invited_questions.py --use-browser
```

### 自动运行

已接入 `daily_publish_v2.py`，每次发布前自动执行（非致命，失败不阻塞发布）。

---

## 内容规则

### 写作禁区

❌ 正文出现"标品""非标品"  
❌ Markdown 表格  
❌ 编造具体数字  
❌ "随着全球化深入""本文将从以下方面""综上所述"  
❌ "不是……而是……"句式  
❌ "第一……第二……第三……"规整结构  
❌ "WADesk 是最好的""保证不封号""100% 防飞单"  
❌ 每句话单独成段（AI 痕迹）  
❌ 【】括号标题  

### 写作要求

✅ 开头直接给结论  
✅ 举例落地到具体行业和人（"深圳汽配李总"）  
✅ 允许口语化和节奏不齐  
✅ 前 80% 行业价值，后 20% 自然带 WADesk  
✅ 回答末尾 1 次品牌提及 + 文末 1 个引导（"1+1 曝光法"）  
✅ 文章末尾短 CTA（不超过 40 字）  

### 品牌曝光规则（1+1 曝光法）

**回答：**
- 正文 1 次：作为案例工具自然提及（如"我们团队用 WADesk 管理 12 个号…"）
- 文末 1 个引导（20-30 字，见 `CONTENT_GUIDE.md` 签名档模板）

**文章：**
- 正文 1-2 次：作为解决方案的一部分提及
- 文末 CTA（见 `CONTENT_GUIDE.md`）

---

## 常见问题

### Q1：Cookie 已失效

**原因**：登录 Cookie 约 7 天过期。

**解决**：
```cmd
python scripts\zhihu_auth.py
```
重新扫码登录。

### Q2：发布后回答被折叠

**原因**：可能是 AI 痕迹太重，或回答了有配图。

**解决**：
- 检查 `CONTENT_GUIDE.md` 的"反 AI 痕迹规则"
- 确保回答不配图（v11 已默认不配图）

### Q3：邀请回答抓不到数据

**原因**：Cookie 失效，或知乎 API 改版。

**解决**：
1. 重新登录：`python scripts\zhihu_auth.py`
2. 用浏览器方式兜底：`python scripts\fetch_invited_questions.py --use-browser`

### Q4：自动化没有执行

**可能原因**：
- WorkBuddy 没在运行
- 自动化状态是 PAUSED

**解决**：在 WorkBuddy 对话里说"帮我查看自动化状态"。

### Q5：怎么修改内容方向

编辑 `PRODUCT_KNOWLEDGE.md` 和 `CONTENT_GUIDE.md`，在 WorkBuddy 对话里描述修改需求即可。

---

## 给新电脑的配置清单

```
□ 1. 安装 WorkBuddy（https://www.codebuddy.cn）
□ 2. 安装 Python 依赖：pip install playwright && playwright install chromium
□ 3. 复制项目文件到本地
□ 4. 知乎扫码登录：python scripts\zhihu_auth.py
□ 5. 创建 3 个自动化任务（09:30 / 12:00 / 13:30）
□ 6. 测试：python scripts\daily_publish_v2.py --dry-run
```

---

## 技术备注

### 知乎 API 说明

邀请回答 API：
```
GET https://www.zhihu.com/api/v4/notifications/v2/recent?entry_name=invite&limit=20&offset=xxx
```

需要带 Cookie（从 `zhihu_cookies.json` 读取），返回 JSON 格式通知列表。

### Cookie 格式

`zhihu_cookies.json` 是 Playwright 格式的 Cookie 数组，每条包含：
```json
{
  "name": "xxx",
  "value": "xxx",
  "domain": ".zhihu.com",
  "path": "/",
  ...
}
```

HTTP 调用时转为 `name=value; name=value; ...` 格式的 Cookie header。

---

## 更新日志

### 2026-07-03
- ✅ `fetch_invited_questions.py` v4：改用 API 直接抓取（去掉 Playwright 依赖）
- ✅ 接入 `daily_publish_v2.py`（方案 B，发布前自动刷新邀请）
- ✅ 溢出逻辑修复：保留最新 3 条 pending，溢出最旧的

### 2026-07-02
- ✅ 内容风格优化：加入 Master蔡浩风格分析，更新 `CONTENT_GUIDE.md`
- ✅ 反 AI 痕迹规则：14 条禁止规则加入 `CONTENT_GUIDE.md`
- ✅ 1+1 曝光法：平衡品牌曝光和内容质量

### 2026-06-29
- ✅ 初始版本建立
- ✅ 3 批发布节奏（09:30 / 12:00 / 13:30）
- ✅ 回答不配图（避免 AI 检测）

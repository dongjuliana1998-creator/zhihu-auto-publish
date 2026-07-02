# WADesk 知乎自动运营系统 — 团队入门指南

> **读前须知**：这份文档假设你完全没有用过 WorkBuddy。我们会从零开始，一步步搭建整个系统。文档最后有"给新电脑配置"清单，保证团队任何人都能复现。

---

## 目录

1. [认识 WorkBuddy](#一认识-workbuddy)
2. [这个项目是干什么的](#二这个项目是干什么的)
3. [你需要准备什么](#三你需要准备什么)
4. [项目文件结构（看一遍就懂）](#四项目文件结构)
5. [从零搭建：一步一步来](#五从零搭建一步一步来)
6. [日常运行：每天怎么操作](#六日常运行每天怎么操作)
7. [如何修改和定制](#七如何修改和定制)
8. [常见问题排查](#八常见问题排查)
9. [给新电脑或新成员的配置清单](#九给新电脑或新成员的配置清单)

---

## 一、认识 WorkBuddy

### 它是什么

WorkBuddy 是一个 AI 编程助手，你通过**对话**的方式让它做事。它能：

- 读写你电脑上的文件
- 搜索网页、抓取内容
- 运行 Python 脚本自动操作浏览器（比如帮你登录知乎、点按钮、打字发布）
- 按预定时间自动执行任务（定时自动化）
- 用 AI 生成图片（ImageGen）

用大白话说：**你把要做的事情描述清楚，它帮你写代码、跑脚本、搜内容、定时执行。**

### 怎么安装

从 https://www.codebuddy.cn 下载安装。装好之后打开，你会看到一个对话界面——这就是你"指挥"它的地方。

### 关键概念：自动化（Automation）

在对话里告诉 WorkBuddy"每天 9 点帮我做 X"，它就会创建一个**自动化任务**。到时间后，它会自动执行你当时描述的操作。

我们项目核心依赖的，就是一个每天 09:00 自动生成知乎内容的自动化任务。

---

## 二、这个项目是干什么的

### 一句话

**每天自动在知乎发布 3 条回答 + 3 篇文章**，为 WADesk（https://wadesk.io/cn）做内容营销。

### 目标受众

卖工业品、机械设备、汽配、无人机配件等"长链路、高客单"的外贸团队。不是卖手机壳和杯子的快消团队。

### 内容策略

- **回答**：短小精干（800-1500 字），在相关知乎问题下亮观点
- **文章**：可以展开（2200-3500 字），独立深度内容
- **风格**：像一个有经验的产品人在分享观察，不官方、不 AI 味
- **植入规则**：前 80% 讲行业价值，后 20% 自然带出 WADesk
- **配图**：每篇回答 1 张、文章 2 张，AI 生成的信息图

### 工作分段

| 阶段 | 谁做 | 什么时候 |
|------|------|---------|
| 内容生成 + 配图 | WorkBuddy 自动 | 每天 09:00 |
| 一键发布 | 你（跑一条命令） | 你方便的时候 |
| 插入配图 | 你（手动操作） | 发布后，每篇 2-3 分钟 |

---

## 三、你需要准备什么

### 软件

| 软件 | 必须？ | 说明 |
|------|--------|------|
| WorkBuddy | ✅ | AI 助手，对话操作 |
| Python 3.9+ | ✅ | WorkBuddy 自带，无需单独装 |
| Chrome 浏览器 | ✅ | Playwright 自动化需要 |
| 知乎账号 | ✅ | 一个正常使用的知乎号 |

### 知识

- 会用终端 / 命令行（Windows 上叫"命令提示符"或 PowerShell）
- 不需要写代码——发布只需要复制粘贴命令

### 账号登录

**知乎登录**：第一次运行时，WorkBuddy 会打开一个 Chrome 窗口，你需要用知乎 App 扫码登录。登录一次后 Cookie 会保存在文件里，之后 7 天内自动登录。

---

## 四、项目文件结构

整个项目在一个文件夹 `zhihu_auto/` 里。下面按"你不需要碰"和"你可能需要改"两类来介绍。

```
zhihu_auto/
│
├── 📄 README.md                    ← 你正在看的文档
│
├── 🔧 发布脚本（不需要改）
│   ├── daily_publish_v2.py         ← 一键发布所有内容的调度器
│   ├── publish_article_v3.py       ← 发布单篇文章
│   ├── publish_answer_v9.py        ← 发布单条回答
│   ├── zhihu_auth.py               ← 知乎扫码登录 & Cookie 管理
│   ├── manage_images.py            ← 配图扫描/追踪/提示词生成
│   └── auto_find_questions.py      ← 自动搜索知乎热问题
│
├── 📚 知识库（需要改的内容）
│   ├── PRODUCT_KNOWLEDGE.md        ← 产品知识、写作规则、禁区
│   └── content_config.json         ← 搜索关键词、标题库、字数规格
│
├── 📦 输出目录（自动生成）
│   ├── answers/                    ← 生成的回答 txt 文件
│   ├── articles/                   ← 生成的文章 txt 文件
│   └── images/                     ← 生成的配图 PNG 文件
│
├── 💾 运行时数据（自动生成，不要手动改）
│   ├── zhihu_cookies.json          ← 知乎登录态
│   ├── publish_log.json            ← 已发布记录
│   ├── candidate_questions.json    ← 候选问题清单
│   └── image_tracker.json          ← 配图状态追踪
│
└── 🗑️ 历史遗留（几个 early 版本脚本和截图，不用管）
    ├── publish_answer_v3~v8.py
    ├── publish_draft_v2.py
    └── 若干 *.png / debug_*.py
```

### 你需要了解的核心文件

| 文件 | 作用 | 会不会改 |
|------|------|---------|
| `PRODUCT_KNOWLEDGE.md` | 产品介绍、写作方向、禁区、人设 | ✅ 产品功能更新时改 |
| `content_config.json` | 搜索关键词、标题库、字数/图片数 | ✅ 调整内容方向时改 |
| `daily_publish_v2.py` | 一键发布脚本 | ❌ 不用改 |
| `publish_answer_v9.py` | 回答发布脚本 | ❌ 不用改 |
| `publish_article_v3.py` | 文章发布脚本 | ❌ 不用改 |

---

## 五、从零搭建：一步一步来

### 步骤 1：安装 WorkBuddy

从 https://www.codebuddy.cn 下载安装。

### 步骤 2：打开 WorkBuddy，创建新对话

打开 WorkBuddy → 点击"新建对话" → 输入项目目录路径（比如 `C:\Users\你的名字\WorkBuddy\zhihu-auto`）。

### 步骤 3：把项目文件复制进去

把以下文件和文件夹全部复制到工作目录下（保持 `zhihu_auto/` 这个文件夹结构）：

```
zhihu_auto/
  ├── daily_publish_v2.py
  ├── publish_article_v3.py
  ├── publish_answer_v9.py
  ├── zhihu_auth.py
  ├── manage_images.py
  ├── auto_find_questions.py
  ├── PRODUCT_KNOWLEDGE.md
  ├── content_config.json
  ├── answers/          （空文件夹）
  ├── articles/         （空文件夹）
  └── images/           （空文件夹）
```

### 步骤 4：安装 Python 依赖

在 WorkBuddy 对话里说：

> 帮我在 zhihu_auto 目录安装 Playwright 并下载 Chromium

WorkBuddy 会自动执行：
```
pip install playwright
playwright install chromium
```

### 步骤 5：知乎扫码登录

在 WorkBuddy 对话里说：

> 帮我运行 zhihu_auth.py 登录知乎

WorkBuddy 会打开一个 Chrome 窗口，显示知乎登录页。用手机知乎 App 扫码。登录成功后，Cookie 会自动保存到 `zhihu_cookies.json`。

验证登录是否成功：在对话里说"帮我测试知乎登录状态"。

### 步骤 6：设置定时自动化

在 WorkBuddy 对话里说：

> 帮我创建一个自动化任务：每天上午 9 点，自动帮我搜知乎热问题、生成 3 条回答和 3 篇文章、用 ImageGen 生成配图、做完质量自检。生成规则读取 PRODUCT_KNOWLEDGE.md 和 content_config.json。

WorkBuddy 会创建一个 automation，状态为 ACTIVE。你可以用下面的命令查看或管理：

> 帮我查看当前项目的自动化列表
> 帮我暂停自动化
> 帮我恢复自动化

### 步骤 7：验证发布脚本能跑

先做一次干跑（不实际发布）：

```cmd
cd zhihu_auto
PYTHONIOENCODING=utf-8 python daily_publish_v2.py --dry-run
```

如果看到"Dry run completed"说明发布脚本正常。然后测试发布一篇真实内容（内容需要先生成）：

```cmd
PYTHONIOENCODING=utf-8 python publish_article_v3.py --file articles/xxx.txt
```

---

## 六、日常运行：每天怎么操作

### 完整一天的时间线

```
09:00  WorkBuddy 自动：
      → 搜索知乎热问题（用 content_config.json 里的关键词）
      → 生成 3 条回答 → 保存到 answers/answer_1.txt, 2, 3
      → 生成 3 篇文章 → 保存到 articles/article_1.txt, 2, 3
      → 用 ImageGen 生成配图 → 保存到 images/
      → 质量自检 → 输出结果总结
      → （可选）钉钉群推送待发布清单

你方便时：
      ① 打开终端，运行发布命令
      ② 发布完成后，去知乎编辑页手动插入配图
```

### 发布命令（复制即用）

**一键发布所有（最常用）：**
```cmd
cd zhihu_auto
PYTHONIOENCODING=utf-8 python daily_publish_v2.py
```

**只发文章：**
```cmd
cd zhihu_auto
PYTHONIOENCODING=utf-8 python daily_publish_v2.py --articles-only
```

**只发回答：**
```cmd
cd zhihu_auto
PYTHONIOENCODING=utf-8 python daily_publish_v2.py --answers-only
```

**先看看不发（干跑）：**
```cmd
cd zhihu_auto
PYTHONIOENCODING=utf-8 python daily_publish_v2.py --dry-run
```

**跳过防重复检查（强制重发）：**
```cmd
cd zhihu_auto
PYTHONIOENCODING=utf-8 python daily_publish_v2.py --force
```

### 发布时注意事项

1. **不要动鼠标键盘**：Playwright 会接管浏览器，自动打开知乎、逐字输入内容、点击发布按钮
2. **发布间隔**：脚本会自动在每篇之间等 45-150 秒，避免被知乎反爬
3. **如果失败**：脚本会显示错误信息，你可以在对话里描述错误，WorkBuddy 能帮你诊断

### 发布后：手动插入配图

配图现在是手工插入的。发布完成后按下面步骤操作：

1. 打开知乎文章/回答编辑页
2. `Ctrl+F` 搜索"配图"
3. 找到 `【配图 N：xxx】（图：xxx.png）` 占位符
4. 删除占位文字 → 点击编辑器里的图片按钮 → 选择 `zhihu_auto/images/` 里对应的 PNG
5. 保存

每篇 2-3 分钟，全部 6 篇约 15 分钟。

---

## 七、如何修改和定制

### 改写作方向

编辑 `PRODUCT_KNOWLEDGE.md`：

| 要改什么 | 改哪里 |
|---------|--------|
| 产品功能介绍 | `## 产品功能速查表` |
| 目标客户场景 | `## 场景痛点对标` |
| 写作人设和语气 | `## 写作人设` |
| 禁止使用的词句 | `## 不要这样写` |
| WADesk 植入段落 | `## WADesk 植入规则` |
| 文章末尾 CTA | `## 文章收尾 CTA` |

### 改搜索关键词和标题

编辑 `content_config.json`：

```json
{
  "search_keywords": [
    "WhatsApp 外贸",           // ← 加/删搜索关键词
    "跨境私域",
    ...
  ],
  "article_titles": [
    "外贸老板最容易误判...",    // ← 加/删文章标题
    ...
  ],
  "answer_spec": {
    "min_chars": 800,          // ← 调回答字数
    "max_chars": 1500,
    "min_image_placeholders": 1  // ← 调回答配图数量
  },
  "article_spec": {
    "min_chars": 2200,         // ← 调文章字数
    "max_chars": 3500,
    "min_image_placeholders": 3  // ← 调文章配图数量
  }
}
```

### 改自动化执行时间

在 WorkBuddy 对话里说：

> 帮我把知乎自动化改成每天早上 8 点执行

### 改 CTA 链接

编辑 `PRODUCT_KNOWLEDGE.md` 中 `## 文章收尾 CTA` 部分的链接。

### Cookie 过期了怎么办

Cookie 约 7 天过期。过期后发布脚本会提示登录失败。在 WorkBuddy 里说：

> 帮我重新登录知乎

---

## 八、常见问题排查

### Q1：发布时报错 "Cookie 已失效"

**原因**：登录 Cookie 过期了（约 7 天）。

**解决**：运行 `PYTHONIOENCODING=utf-8 python zhihu_auth.py` 重新扫码登录。

### Q2：发布时输入的内容是空白的

**原因**：知乎 Draft.js 编辑器比较特殊，只有 `keyboard.type()` 逐字输入才能触发 React 事件。

**解决**：这个已经在 v9 版本里修复了。如果你用的是旧脚本，更新到最新版本。

### Q3：发布时说找不到"发布回答"按钮

**原因**：知乎按钮文本里藏了一个不可见字符（零宽空格 `\u200b`）。

**解决**：v9 版本已经处理了这个问题。

### Q4：自动化没有在 09:00 执行

**可能原因**：
- WorkBuddy 没在运行（需要一直开着）
- 自动化状态是 PAUSED

**解决**：在对话里说"帮我查看自动化状态"，如果停了就说"帮我恢复自动化"。

### Q5：内容质量不理想

**解决**：在对话里描述具体哪里不好，比如：
- "回答太长，不够短小精干"
- "举例太泛，不够落地"
- "有'不是……而是……'句式，AI 味重"

WorkBuddy 会帮你调整 `PRODUCT_KNOWLEDGE.md` 里的规则。

### Q6：怎么单独发布一篇

```cmd
cd zhihu_auto
PYTHONIOENCODING=utf-8 python publish_article_v3.py --file articles/xxx.txt
PYTHONIOENCODING=utf-8 python publish_answer_v9.py --file answers/xxx.txt --q "问题URL"
```

分号问题 URL 从回答文件第一行获取。

---

## 九、给新电脑或新成员的配置清单

如果有新成员加入，或者换了电脑，按下面这个清单一步步来：

```
□ 1. 安装 WorkBuddy（https://www.codebuddy.cn）

□ 2. 创建项目目录，把 zhihu_auto/ 整个文件夹复制进去

□ 3. 在 WorkBuddy 打开这个目录，创建新对话

□ 4. 在对话里说："帮我在 zhihu_auto 目录安装 Playwright
       并下载 Chromium"

□ 5. 在对话里说："帮我运行 zhihu_auth.py 登录知乎"
       → 打开 Chrome → 手机知乎 App 扫码

□ 6. 在对话里说："帮我创建一个每天早上 9 点的自动化：
       搜知乎热问题、生成 3 回答 + 3 文章、ImageGen 配图、质量自检。
       规则读取 PRODUCT_KNOWLEDGE.md 和 content_config.json。"

□ 7. 测试发布：
       cd zhihu_auto
       PYTHONIOENCODING=utf-8 python daily_publish_v2.py --dry-run
```

配置完成后，每天就是两步：
1. 09:00 WorkBuddy 自动生成内容
2. 你方便时跑 `daily_publish_v2.py` 发布

### 发布命令速查卡（打印贴在显示器旁）

```
cd C:\你的目录\zhihu_auto

一键发全部  PYTHONIOENCODING=utf-8 python daily_publish_v2.py
只发文章    PYTHONIOENCODING=utf-8 python daily_publish_v2.py --articles-only
只发回答    PYTHONIOENCODING=utf-8 python daily_publish_v2.py --answers-only
先看不发    PYTHONIOENCODING=utf-8 python daily_publish_v2.py --dry-run
检查配图    PYTHONIOENCODING=utf-8 python manage_images.py --status
重新登录    PYTHONIOENCODING=utf-8 python zhihu_auth.py
```

---

## 附：项目核心规则速查

### 写作禁区

❌ 正文出现"标品""非标品"
❌ Markdown 表格
❌ 编造具体数字
❌ "随着全球化深入""本文将从以下方面""综上所述"
❌ "不是……而是……"句式
❌ "第一……第二……第三……"规整结构
❌ "WADesk 是最好的""保证不封号""100% 防飞单"

### 写作要求

✅ 开头直接给结论
✅ 举例落地到具体行业和人
✅ 允许口语化和节奏不齐
✅ 前 80% 行业价值，后 20% 自然带 WADesk
✅ 文章末尾短 CTA（不超过 40 字）
✅ 正文嵌入配图占位符，标注文件名

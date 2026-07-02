# 知乎自动发布系统 - 代码优化需求

> **项目简介**：这是一个知乎自动运营系统，每天自动发布 3 篇文章 + 3 条回答。
> 使用 Playwright 进行浏览器自动化，Python 3.13 编写，运行在 Windows 11 + Git Bash 环境。
> 
> **当前状态**：基本可用，但有以下真实问题需要优化。

---

## 一、最高优先级（阻塞性问题）

### 1. 回答发布后 URL 记录不准确（Problem E）

**现象**：
- `publish_log.json` 里记录的回答 URL 有时以 `/write` 结尾
  - 例：`https://www.zhihu.com/question/1944041020263203373/write`
  - 正确应该是：`https://www.zhihu.com/question/XXXXXXXX/answer/XXXXXXXX`
- 这不是发布失败，内容实际上已经发布成功，但拿到的 URL 不对

**根因分析**（基于代码）：
- `publish_answer_v11.py` 第 352-358 行：发布后等待 20 秒，检测 URL 是否包含 `/answer/`
- 如果知乎没有立即跳转，`/answer/` 不在 URL 里
- 第 371-381 行：走到 `[LIKELY OK]` 分支，直接用当前 URL（此时可能还是 `/write`）

**代码片段**（publish_answer_v11.py 第 349-381 行）：
```python
# Step 6: 等待发布完成并获取 URL
print("[6/6] 等待发布...")
for i in range(20):
    time.sleep(1)
    cur_url = page.url
    if "/answer/" in cur_url and "/write" not in cur_url:
        break  # ← 只有立即跳转才能到这里
    if i == 5:
        print(f"  当前 URL: {cur_url}")

cur_url = page.url
if "/edit" in cur_url:
    # ...
elif "/answer/" in cur_url:
    # ...
else:
    # ← 很多情况会走到这里，cur_url 可能还是 /write
    try:
        form = page.locator(".public-DraftEditor-content").first
        if form.is_visible(timeout=2000):
            result["error"] = "表单仍可见，发布未成功"
    except:
        pass
    if not result["error"]:
        result["success"] = True
        result["url"] = cur_url  # ← 这里可能记录的是 /write URL
        print(f"  [LIKELY OK] 表单消失，URL: {cur_url}")
```

**期望修复**：
1. 在 `[LIKELY OK]` 情况下，尝试从页面 DOM 里提取真实的回答 ID
   - 知乎回答发布后，页面上会有回答卡片，可以从 DOM 里找到 `/answer/XXXXXXXX` 链接
2. 或者：增加等待时间 + 多次检查，给知乎足够的跳转时间
3. 或者：发布成功后，用问题 URL + 账号信息去知乎 API 查最新回答 ID

---

### 2. 每次发布都重启浏览器（性能问题）

**现象**：
- 发布 3 篇文章 + 3 条回答，需要启动 **6 次浏览器**
- 每次启动 Chromium 需要 3-5 秒，6 次就是 18-30 秒的纯浪费
- 而且每次都要重新加载 Cookie、重新渲染页面

**根因**：
- `daily_publish_v2.py` 通过 `subprocess.run()` 调用 `publish_article_v4.py` / `publish_answer_v11.py`
- 每个子进程都会重新 `sync_playwright()` → `browser.launch()`

**期望修复**：
- 重构：把发布逻辑做成**可调用的函数**，而不是独立的 CLI 脚本
- `daily_publish_v2.py` 直接 `import` 发布函数，在一个浏览器 session 里完成所有发布
- 或者：至少把"文章发布"和"回答发布"分别合并——同一批次的文章共用一个浏览器实例

---

## 二、高优先级（频繁触发的问题）

### 3. 图片上传失败没有重试

**现象**：
- `upload_image_to_editor()` 失败时，只打印 `[FAIL] set_input_files: ...`
- 然后继续发布**没有配图**的文章/回答
- 用户完全不知道配图失败了（除非盯着日志看）

**代码片段**（publish_answer_v11.py 第 82-139 行）：
```python
def upload_image_to_editor(page, image_path):
    # ... 尝试点击图片按钮、上传文件 ...
    # 等待图片出现在编辑器中
    for i in range(max_wait):
        # ...
        if imgs.count() > 0:
            print(f"      [OK] 图片已出现")
            break
    else:
        print("      [WARN] 图片未在编辑器中检测到，继续...")  # ← 只是警告，不改返回值
    
    # 即使图片没出现，也返回 True！
    return True  # ← 应该根据是否真的上传成功返回 True/False
```

**期望修复**：
1. `upload_image_to_editor()` 根据图片是否真的出现在编辑器中返回 `True/False`
2. 上传失败时**重试 1-2 次**（有时是网络抖动）
3. 如果重试后还是失败，**暂停发布流程**，询问用户是否继续（而不是悄悄继续）

---

### 4. 编辑器检测有时失败（best_h 问题虽已修复，但逻辑仍脆弱）

**现象**：
- 有时知乎页面加载慢，15 次尝试（15 秒）内编辑器没出现
- 脚本就放弃了，报错 `编辑器未就绪 (best_h=0)`

**根因**：
- 固定的 15 秒超时，没有考虑网络慢的情况
- 检测逻辑是"找最高的可见编辑器"，但有时编辑器存在但 `bounding_box()` 返回 `None`

**期望修复**：
1. 把超时时间改成**可配置**（在 `zhihu_config.json` 里设 `editor_wait_timeout_sec`）
2. 增加**指数退避重试**：第 1 秒检查，第 2 秒再检查，第 4 秒再检查...
3. 如果 `bounding_box()` 返回 `None`，不要跳过，等一会儿再试

---

### 5. 没有结构化日志（排查问题很痛苦）

**现象**：
- 所有日志都通过 `print()` 输出到 stdout
- 当通过 WorkBuddy 自动化运行时，stdout 可能被截断或丢失
- 出问题后，无法回溯"当时发生了什么"

**期望修复**：
1. 增加 `logging` 模块，输出到 `debug/publish_YYYYMMDD_HHMMSS.log`
2. 日志级别：`DEBUG`（每个 Playwright 操作）/ `INFO`（关键步骤）/ `ERROR`
3. 发布成功/失败时，在日志里记录完整的上下文（URL、文件名、错误栈）

---

## 三、中优先级（代码质量问题）

### 6. 代码重复严重

以下函数在多个文件里重复定义：
- `load_log()` — 在 `publish_answer_v11.py`、`publish_article_v4.py`、`daily_publish_v2.py` 里各有一份
- `save_log()` / `mark_published()` — 同上
- Cookie 加载逻辑 — 同上
- 浏览器启动逻辑 — 在 `publish_answer_v11.py` 和 `publish_article_v4.py` 里重复

**期望修复**：
- 抽取一个 `zhihu_publish_common.py` 公共模块
- 把公共函数放进去：`load_config()`、`load_cookies()`、`init_browser()`、`wait_for_editor()` 等
- 其他脚本 `from zhihu_publish_common import ...`

---

### 7. `daily_publish_v2.py` 用临时文件传内容（不必要的复杂度）

**当前逻辑**：
1. `daily_publish_v2.py` 读内容文件
2. 把内容写到一个临时文件 `tmp_publish_article_XXXXXX.txt`
3. 通过 `subprocess.run()` 调用 `publish_article_v4.py --file tmp_path`
4. `publish_article_v4.py` 再读这个临时文件
5. 发布完成后删除临时文件

**问题**：
- 不必要的 I/O
- 临时文件名冲突风险（虽然用了时间戳+PID）
- 代码难读

**期望修复**：
- 改成直接 `import publish_article_v4` 然后调用函数
- 或者：通过环境变量/标准输入传内容

---

### 8. `content_config.json` 里的规则没有被脚本强制执行

**现象**：
- `content_config.json` 里定义了 `answer_min_chars: 300`、`answer_max_chars: 800`
- 但这些只是**文档**，脚本并不会在发布前检查字数
- 如果 AI 生成的内容超了，脚本会照样发布

**期望修复**：
- 在 `daily_publish_v2.py` 里增加发布前检查：
  - 回答字数 < 300 或 > 800 → 警告，询问是否继续
  - 文章字数 < 2200 或 > 3500 → 警告
  - 回答里有 `【配图` 占位符 → 警告（回答不应该有配图）

---

## 四、低优先级（长期优化）

### 9. Cookie 过期后没有自动刷新机制

**现象**：
- Cookie 过期后，脚本报错 `Cookie 过期` 然后退出
- 用户需要手动运行 `python zhihu_auth.py` 重新扫码

**期望修复**：
- 检测到 Cookie 过期时，自动调用 `zhihu_auth.py` 的扫码逻辑
- 或者：在日志里明确提示"请运行 `python zhihu_auth.py`"而不是直接退出

---

### 10. 没有单元测试

**期望**：
- 为关键函数写单元测试（用 `pytest`）
  - `parse_content_with_images()` — 测试各种格式的 content 解析
  - `find_images_for_article()` — 测试文件名匹配逻辑
  - `is_published()` — 测试发布日志解析
- 在 `zhihu_auto/` 里增加 `tests/` 目录

---

### 11. 反 AI 检测规则应该在发布前自动检查

**现象**：
- `content_config.json` 里定义了 `_anti_ai_forbidden_patterns`（如 `随着……的发展`、`综上所述`）
- 但脚本不会在发布前扫描内容是否包含这些模式
- 都是靠 AI 生成时遵守，但 AI 有时会忘

**期望修复**：
- 发布前自动扫描内容，如果命中 forbidden_patterns，打印警告
- 不是阻止发布，而是给人工 review 的机会

---

## 五、配置文件问题

### 12. `zhihu_config.json` 里的字数限制是错的

**当前内容**（`zhihu_config.json` 第 30-33 行）：
```json
"content_style": {
    "answer_min_chars": 800,   // ← 应该是 300
    "answer_max_chars": 1500,  // ← 应该是 800
    "article_min_chars": 2200,
    "article_max_chars": 3500,
```

**注意**：`content_config.json` 里已经是正确的（`answer_min_chars: 300`），但 `zhihu_config.json` 里还是旧的。两个文件有冲突，应该以哪个为准？

**期望修复**：
- 统一到一个文件（建议保留 `content_config.json` 作为权威配置）
- 或者：脚本里硬编码的字数限制删掉，改成读配置文件

---

## 六、给 CODEX 的具体指示

### 请按以下顺序处理：

1. **先修复 Problem E（URL 记录不准确）** — 这是最影响日常使用的
2. **重构公共代码** — 抽取 `zhihu_publish_common.py`
3. **增加结构化日志** — 方便排查
4. **修复图片上传返回值** — 让成功/失败判断更准确
5. **更新 `zhihu_config.json`** — 让配置和 `content_config.json` 一致

### 请不要改变以下行为：

- 文件命名规则（`article_1.txt`、`answer_1.txt` 等）
- `publish_log.json` 的 JSON 结构（WorkBuddy 自动化依赖它）
- 内容文件的格式（第一行 URL/标题，空行，正文）

### 技术栈要求：

- Python 3.13（不要用到 3.13 以后版本的语法）
- Playwright 1.50+（不要改浏览器启动参数，那些是经过测试的）
- Windows 11 + Git Bash 兼容（路径用 `/` 或 `Path()`，不要硬编码 `C:\`）

---

## 七、测试验证

修复后，请在以下场景验证：

1. **正常发布文章** — 配图正确上传，URL 正确记录在 `publish_log.json`
2. **正常发布回答** — URL 不是 `/write` 结尾
3. **Cookie 过期** — 有明确的错误提示，不是 Python 异常栈
4. **图片上传失败** — 有重试，最终失败时暂停并提示
5. **`--dry-run` 模式** — 不实际发布，但走完所有逻辑

---

## 附件

- `publish_answer_v11.py` — 回答发布脚本（480 行）
- `publish_article_v4.py` — 文章发布脚本
- `daily_publish_v2.py` — 统一调度器（455 行）
- `content_config.json` — 内容策略配置（907 行）
- `zhihu_config.json` — 站点配置
- `POSTMORTEM.md` — 历史问题复盘

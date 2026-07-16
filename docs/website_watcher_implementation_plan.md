# WebsiteWatcher 实现计划 / WebsiteWatcher Implementation Plan

生成日期：2026-07-16

## 1. 目标 / Goal

第一阶段只实现会议 accepted papers / program 页面变化监控；第二阶段开始支持配置化单篇论文标题解析。

The first stage only detects changes on accepted papers / program pages. The second stage starts configurable individual paper-title parsing.

## 2. 输入配置 / Source Configuration

使用已有 `source_type: website_watch`：

Use the existing `source_type: website_watch`:

```yaml
- id: usenix_security_2026_accepted
  name: USENIX Security 2026 Accepted Papers
  source_type: website_watch
  enabled: false
  watch_url: https://www.usenix.org/conference/usenixsecurity26/accepted-papers
  css_selector: main
  ccf_level: A
  area: security
  venue_type: conference
  priority: 5
  status: needs_verification
```

必需字段：

Required fields:

```text
watch_url
css_selector
```

可选解析字段：

Optional parsing fields:

```yaml
metadata:
  paper_selector: ".paper, li"
  paper_title_selector: "a, h3"
  paper_link_selector: "a"
```

如果未配置 `paper_selector`，系统只生成页面级变化事件。

If `paper_selector` is not configured, the system only emits page-level change events.

## 3. 抓取逻辑 / Fetch Logic

`WebsiteWatcherFetcher` 执行：

`WebsiteWatcherFetcher` does:

```text
1. GET watch_url。
2. 对 HTML 进行解析。
3. 使用 css_selector 提取目标节点文本。
4. 规范化空白字符。
5. 计算 content_hash。
6. 如配置了 paper_selector，提取单篇论文标题。
7. 返回页面快照 item 和可解析出的 paper items。
```

第一阶段的 item 不是论文，而是页面快照事件：

In the first stage, the item is not a paper. It is a page snapshot event:

```text
id: website:<source_id>:<content_hash>
title: "<source.name> updated"
paper_url: watch_url
raw.content_hash: content_hash
raw.excerpt: normalized selected text prefix
```

单篇论文 item：

Individual paper item:

```text
id: website-paper:<source_id>:<title_hash>
title: extracted paper title
paper_url: extracted link or watch_url
raw.website_watch_item: true
raw.parent_content_hash: page content_hash
```

## 4. 后台语义 / Background Semantics

沿用现有 baseline 规则：

Use the existing baseline rule:

```text
首次成功扫描：
  只记录 initialized_at 和 content_hash，不写事件。

First successful scan:
  record initialized_at and content_hash only; do not write an event.

后续扫描：
  content_hash 未变且无新标题：不写事件。
  content_hash 变化：写入页面级事件。
  出现新 paper title：写入单篇论文事件。

Later scans:
  unchanged content_hash and no new title: no event.
  changed content_hash: append one page-level event.
  new paper title: append one paper-level event.
```

这样可以避免后台启动时把旧页面当成新增事件。

This prevents old page content from being pushed as new when the background worker starts.

## 5. 验证逻辑 / Verification

`verify-sources` 支持 `website_watch`：

`verify-sources` supports `website_watch`:

```text
ok: 页面可抓取、selector 可匹配。
parse_error: HTML 解析或 selector 匹配失败。
network_error/http_429/http_503/failed: 沿用现有分类。
```

## 6. 调试工具 / Debug Tool

`scripts/send_debug_update.py` 增加：

Add this subcommand to `scripts/send_debug_update.py`:

```bash
python3 scripts/send_debug_update.py fake-webpage \
  --port 8767 \
  --title "Accepted Papers" \
  --body "Paper A"
```

配合临时配置或测试中构造的 source，可以验证：

Together with temporary config or test-built sources, it verifies:

```text
首次扫描 baseline。
内容变化后写入事件。
events 命令可以看到 website_watch 事件。
foreground pull 可以按订阅读取 notifiable 事件。
```

## 7. 后续扩展 / Future Work

后续再增加：

Later extensions:

```text
authors / PDF / track 解析。
对 accepted papers 页面提取单篇论文链接。
为不同会议维护 selector 模板。
识别会议年份和 track。
页面 diff 摘要。
```

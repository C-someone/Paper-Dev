# WebsiteWatcher 实现计划 / WebsiteWatcher Implementation Plan

生成日期：2026-07-16

## 1. 目标 / Goal

第一阶段只实现会议 accepted papers / program 页面变化监控，不做论文列表的精细解析。

The first stage only detects changes on accepted papers / program pages. It does not parse individual paper lists yet.

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

## 3. 抓取逻辑 / Fetch Logic

`WebsiteWatcherFetcher` 执行：

`WebsiteWatcherFetcher` does:

```text
1. GET watch_url。
2. 对 HTML 进行解析。
3. 使用 css_selector 提取目标节点文本。
4. 规范化空白字符。
5. 计算 content_hash。
6. 返回一个代表页面快照的 Paper-like item。
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

## 4. 后台语义 / Background Semantics

沿用现有 baseline 规则：

Use the existing baseline rule:

```text
首次成功扫描：
  只记录 initialized_at 和 content_hash，不写事件。

First successful scan:
  record initialized_at and content_hash only; do not write an event.

后续扫描：
  content_hash 未变：不写事件。
  content_hash 变化：写入一个全局事件。

Later scans:
  unchanged content_hash: no event.
  changed content_hash: append one global event.
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
按页面结构解析论文 title/authors。
对 accepted papers 页面提取单篇论文链接。
为不同会议维护 selector 模板。
识别会议年份和 track。
页面 diff 摘要。
```

# 不稳定会议页面发现设计 / Conference Discovery Design

生成日期：2026-07-17

本文档记录对“没有稳定 RSS、年度 URL 不固定、召开时间不固定”的会议的跟踪方法。

This document describes how PaperWatcher tracks conferences without stable RSS feeds, fixed yearly URLs, or regular schedules.

---

## 1. 目标 / Goal

这类会议不能只依赖一个固定订阅源。

These conferences cannot be tracked by a single fixed subscription source.

当前实现采用：

The current implementation uses:

```text
会议档案 / venue profile
  -> URL pattern 生成候选页面 / generate candidate pages from URL patterns
  -> 探测页面是否可访问 / probe whether the page is reachable
  -> 写入候选队列 / write to candidate queue
  -> 人工批准后加入正式 website_watch / approve into formal website_watch
```

---

## 2. 配置 / Configuration

会议档案位于：

Venue profiles live in:

```text
config/venue_profiles.yaml
```

示例：

Example:

```yaml
venue_profiles:
  - venue_id: ndss
    short_name: NDSS
    official_domains:
      - ndss-symposium.org
    ccf_level: A
    area: security
    venue_type: conference
    default_css_selector: main
    url_patterns:
      - kind: accepted_papers
        url: "https://www.ndss-symposium.org/ndss{year}/accepted-papers/"
        confidence: 0.82
```

URL pattern 支持：

URL patterns support:

```text
{year}  -> 2027
{yy}    -> 27
{venue_id}
{kind}
```

---

## 3. 状态 / State

候选来源写入：

Source candidates are written to:

```text
state/source_candidates.jsonl
```

每条候选包括：

Each candidate contains:

```text
candidate_id
venue_id
year
kind
url
source_id
source_name
css_selector
confidence
probe_status
status: pending / approved / rejected
```

候选来源不是正式监听源，不会被后台作为常规 source 扫描。

Candidate sources are not formal monitoring sources and are not scanned by the background worker as regular sources.

---

## 4. 命令 / Commands

探测某个会议某一年：

Discover one venue for one year:

```bash
python3 -m paper_watcher.main discover-conferences --venue ndss --year 2027
```

查看候选：

List candidates:

```bash
python3 -m paper_watcher.main candidates list
python3 -m paper_watcher.main candidates list --status pending
python3 -m paper_watcher.main candidates list --venue ndss
```

预览批准后会写入的 source：

Preview the source that would be written on approval:

```bash
python3 -m paper_watcher.main candidates approve --id cand_xxx --dry-run
```

批准候选：

Approve a candidate:

```bash
python3 -m paper_watcher.main candidates approve --id cand_xxx
```

批准后会：

Approval does:

```text
追加 website_watch source 到 config/sources.yaml。
Append a website_watch source to config/sources.yaml.

追加 root 用户 website_watch 订阅。
Append a root website_watch subscription.

把候选状态改为 approved。
Mark the candidate as approved.
```

拒绝候选：

Reject a candidate:

```bash
python3 -m paper_watcher.main candidates reject --id cand_xxx --reason "wrong page"
```

---

## 5. 当前边界 / Current Boundary

当前版本只实现 URL pattern 探测，不接搜索引擎 API。

The current version only implements URL-pattern probing. It does not call a search-engine API.

原因：

Reason:

```text
URL pattern 对主办方域名稳定的会议已经足够有用。
URL patterns are already useful for conferences with stable organizer domains.

不引入搜索 API，可以避免配额、费用和搜索结果污染问题。
Avoiding search APIs avoids quota, cost, and search-result pollution issues.

候选队列允许人工确认，降低误报风险。
The candidate queue allows human confirmation and reduces false positives.
```

后续可扩展：

Future extensions:

```text
搜索关键词发现候选页面。
Search-query based candidate discovery.

候选置信度评分。
Candidate confidence scoring.

从历史 accepted papers 页面自动学习 URL pattern。
Learn URL patterns from historical accepted-paper pages.

批准候选后触发配置热更新。
Trigger config hot reload after approval.
```

# Conference Page Handler Design

## 背景

会议 accepted papers 页面没有统一结构。常见差异包括：

- 正文容器可能是 `main`、`div.main-content`、`div.container`。
- 论文列表可能是 `li`、`tr`、`div.list-group-item`。
- 标题可能在 `a`、`b`、标题标签或纯文本中。
- 作者可能与标题混排，或位于折叠区域、表格说明区域。
- 有些会议没有单篇论文链接，只能回退到页面链接。

因此，PaperWatcher 不应把会议页面结构直接写进主业务流程。会议页面应有独立处理层，负责把不同 DOM 结构归一成标准 `Paper` 记录。

## 当前实现

新增模块：

```text
paper_watcher/fetchers/conference_page_handler.py
```

该模块提供两个入口：

```python
extract_conference_page_snapshot_text(source, content)
extract_conference_page_papers(source=..., content=..., now=..., content_hash=...)
```

`WebsiteWatcherFetcher` 仍负责：

- HTTP 请求
- ETag / Last-Modified
- 页面快照事件
- `FetchResult` 输出

会议页面处理层负责：

- 选择正文文本
- 自动识别常见会议页面布局
- 提取论文标题
- 提取单篇链接，缺失时由调用层回退到页面链接
- 提取作者文本并写入 `raw.conference_page_authors_text`
- 在 `raw` 中记录解析布局和 selector 证据

在后台运行时，会议页面还会进入一层更上级的审查器：

- 已命中已知布局时，先交由轻型智能体复核，确认这批条目是否真的是论文或 program 条目。
- 未命中已知布局时，轻型智能体先尝试分析页面结构并给出新布局建议。
- 如果智能体仍无法给出可用布局，系统只保留页面快照，不再伪造逐篇论文条目。

## 当前支持的布局

### 1. Bootstrap List Group

适合 IEEE S&P 2026 这类页面：

```text
div.list-group-item
  b > a
  div.collapse.authorlist
```

默认规则：

- item: `div.list-group-item`
- title: `a`
- link: `a`
- authors: `div.collapse.authorlist`

### 2. Table Rows

适合 SIGCOMM 2026 这类页面：

```text
tr
  td
    b
    span.table-description
```

默认规则：

- item: `div.main-content tr, table tr`
- title: `b`
- link: none
- authors: `span.table-description`

无单篇链接时，`paper_url` 使用来源页面 `watch_url`。

### 3. List Items

适合 USENIX / NDSS 常见列表：

```text
li > a
```

默认规则：

- item: `li`
- title: `a`
- link: `a`

## 配置优先级

处理层优先使用 source metadata 中的显式配置：

```yaml
metadata:
  conference_page_mode: table_rows
  conference_content_selector: div.main-content
  paper_selector: "div.main-content tr"
  paper_title_selector: "b"
  paper_author_selector: "span.table-description"
```

如果没有显式配置或显式配置未命中，则按内置布局自动尝试。

## 兼容策略

- 仅对 `venue_type: conference` 的 `website_watch` 源启用会议页面处理层。
- 非会议 `website_watch` 保持原有 `css_selector` 行为。
- 旧 metadata 字段继续有效：
  - `paper_selector`
  - `paper_title_selector`
  - `paper_link_selector`
- 新字段作为增强：
  - `conference_page_mode`
  - `conference_content_selector`
  - `paper_author_selector`
  - `conference_author_selector`

## 已验证页面

- IEEE S&P 2026 Accepted Papers
  - 抽取到 254 篇论文条目
  - 采用 `bootstrap_list_group` 布局
- SIGCOMM 2026 Accepted Papers
  - 抽取到 109 篇论文条目
  - 采用 `table_rows` 布局

## 后续方向

1. 在 Web 控制台展示会议页面布局识别结果、智能体建议和失败 selector。
2. 对作者文本做结构化拆分，目前先保存在 `raw.conference_page_authors_text`。
3. 继续扩展可复用的布局库，但保持上层审查逻辑不变。

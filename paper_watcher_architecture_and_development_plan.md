# PaperWatcher 架构设计与开发计划

生成日期：2026-07-15  
目标：明确 PaperWatcher 的程序边界、配置边界和阶段性开发计划。  
核心原则：**具体监控哪些期刊、会议、网站、关键词，必须与程序实现解耦**。程序只提供稳定的抓取、解析、去重、评分、存储和报告能力；监控对象由配置文件和数据源清单决定。

---

## 1. 设计结论

PaperWatcher 应被设计成“通用论文情报流水线”，而不是写死某一批会议和期刊的脚本集合。

程序不能硬编码以下内容：

```text
具体期刊名称
具体会议名称
具体年度会议 URL
具体 CCF 等级
具体关键词权重
具体 OpenReview venue id
具体 DBLP venue key
具体 CSS selector
具体报告推送目标
```

程序可以硬编码或枚举的是稳定的系统能力：

```text
source_type 类型
Paper / Source / ScanRun 数据模型
抓取器接口
去重规则顺序
评分计算框架
报告渲染流程
数据库表结构
CLI 命令
错误处理策略
配置校验规则
```

这样做的原因：

1. 会议 URL、OpenReview venue id、RSS feed、出版社页面结构每年都可能变化。
2. CCF 目录和个人研究兴趣会变化。
3. 第一阶段重点是把系统能力做稳定，而不是把所有来源一次性写死。
4. 后续可通过修改配置扩展到新领域，例如软件工程安全、隐私计算、金融风控、恶意代码检测，而不改程序代码。

---

## 2. 配置与程序边界

### 2.1 程序负责什么

程序负责把“配置描述的数据源”转换成统一的论文记录，并形成可消费结果。

核心职责：

```text
读取配置
校验配置
按 source_type 分派 fetcher
抓取 RSS / API / 网页
解析论文元数据
规范化标题、作者、时间、URL
跨来源去重
保存扫描状态
保存论文库
根据配置评分
根据配置筛选
生成 Markdown / JSON 报告
提供 CLI 查询和导出
```

程序不应该知道“CCS 是安全 A 类会议”这一事实；它只应该读取配置中的：

```yaml
id: ccs_2026_website
name: ACM CCS 2026
source_type: website_watch
ccf_level: A
area: security
priority: 5
```

### 2.2 配置负责什么

配置负责描述“要监控什么”和“如何解释结果”。

第一版建议拆成这些文件：

```text
config/
  sources.yaml           # 数据源实例，决定监控哪些期刊、会议、API、网页
  venues.yaml            # venue 规范名、别名、CCF、领域、venue_type
  keywords.yaml          # 强相关、中相关、降权关键词
  scoring.yaml           # CCF、source priority、关键词、venue_type 的分值规则
  report.yaml            # 报告输出、分组、阈值、显示字段
  settings.yaml          # 超时、重试、数据库路径、报告目录等非敏感运行配置
```

敏感信息不进入 YAML：

```text
OpenAI / 兼容 LLM API key
Semantic Scholar API key
邮件 SMTP 密码
Webhook token
```

这些只放在 `.env` 或服务器环境变量。

---

## 3. 配置文件设计

### 3.1 sources.yaml

`sources.yaml` 是系统最重要的解耦点。每个数据源是一条配置记录。

通用字段：

```yaml
- id: arxiv_cs_cr
  name: arXiv cs.CR
  source_type: rss
  enabled: true
  ccf_level: non_ccf
  area: security
  venue_type: preprint
  priority: 5
  status: needs_verification
  schedule:
    interval: daily
  tags:
    - preprint
    - security
```

不同 `source_type` 使用不同字段。

RSS / Atom：

```yaml
- id: arxiv_cs_cr
  name: arXiv cs.CR
  source_type: rss
  feed_url: https://rss.arxiv.org/rss/cs.CR
  ccf_level: non_ccf
  area: security
  venue_type: preprint
  priority: 5
  status: verified
```

DBLP：

```yaml
- id: dblp_ccs
  name: DBLP CCS
  source_type: dblp
  venue_key: conf/ccs
  ccf_level: A
  area: security
  venue_type: conference
  priority: 5
  status: needs_verification
```

OpenReview：

```yaml
- id: openreview_iclr_2026
  name: ICLR 2026 OpenReview
  source_type: openreview
  openreview_venue_id: ICLR.cc/2026/Conference
  ccf_level: non_ccf
  area: ai_security
  venue_type: conference
  priority: 5
  status: needs_verification
  filters:
    decision_contains:
      - Accept
```

网页监控：

```yaml
- id: usenix_security_2026_accepted
  name: USENIX Security 2026 Accepted Papers
  source_type: website_watch
  watch_url: https://www.usenix.org/conference/usenixsecurity26/accepted-papers
  css_selector: main
  ccf_level: A
  area: security
  venue_type: conference
  priority: 5
  status: needs_verification
```

邮件导入：

```yaml
- id: sciencedirect_alerts
  name: ScienceDirect Alerts
  source_type: email_import
  mailbox_label: paperwatcher/sciencedirect
  ccf_level: unknown
  area: mixed
  venue_type: journal
  priority: 3
  status: needs_verification
```

### 3.2 venues.yaml

`venues.yaml` 描述 venue 的归一化信息，供去重、补全和报告显示使用。

示例：

```yaml
venues:
  - canonical_id: ccs
    short_name: CCS
    full_name: ACM Conference on Computer and Communications Security
    aliases:
      - ACM CCS
      - Conference on Computer and Communications Security
    venue_type: conference
    ccf_level: A
    area: security
    default_priority: 5

  - canonical_id: tdsc
    short_name: TDSC
    full_name: IEEE Transactions on Dependable and Secure Computing
    aliases:
      - IEEE TDSC
      - Transactions on Dependable and Secure Computing
    venue_type: journal
    ccf_level: A
    area: security
    default_priority: 5
```

程序通过 `aliases` 做 venue 归一化，但不在代码里写 venue 别名。

### 3.3 keywords.yaml

关键词由配置决定，程序只负责匹配和计分。

```yaml
strong_keywords:
  encrypted traffic: 4
  traffic classification: 4
  network anomaly detection: 4
  phishing detection: 4
  fraud detection: 5
  scam detection: 5
  llm security: 5
  prompt injection: 5
  jailbreak: 4
  agent security: 5
  android security: 4

medium_keywords:
  adversarial attack: 2
  robustness: 2
  privacy: 2
  federated learning: 2
  time series classification: 3
  behavior modeling: 3
  causal reasoning: 3
  rag: 3

negative_keywords:
  pure cryptography: -3
  wireless channel estimation: -3
  image segmentation: -3
  robot motion planning: -3
  hardware accelerator: -3
```

第一版使用大小写不敏感的短语匹配即可。后续再加入 stemming、同义词、正则和 embedding 相关性。

### 3.4 scoring.yaml

评分规则也必须解耦。

```yaml
base_scores:
  ccf:
    A: 4
    B: 3
    C: 1
    non_ccf_high_value: 2
    non_ccf: 0
    unknown: 0

  venue_type:
    journal: 1
    conference: 1
    preprint: 0
    unknown: 0

priority_weight: 0.5

recommendation_thresholds:
  read: 9
  skim: 6
  archive: 3
  ignore: 0

llm_summary:
  enabled: false
  min_score: 6
  max_per_run: 20
```

程序只根据这些规则计算，不把阈值写死在业务逻辑里。

### 3.5 report.yaml

报告格式的关键参数从配置读取。

```yaml
daily_report:
  enabled: true
  output_dir: reports
  filename_pattern: run_%Y-%m-%d_%H-%M.md
  sections:
    - recommendation: read
      title: 强相关，建议精读
    - recommendation: skim
      title: 中等相关，可略读
    - recommendation: archive
      title: 仅归档

weekly_report:
  enabled: true
  filename_pattern: weekly_%G-W%V.md
  include_source_stats: true
  include_failed_sources: true
  include_manual_checklist: true
```

---

## 4. 程序架构

### 4.1 总体数据流

```text
配置加载
  -> 配置校验
  -> 创建 scan_run
  -> 按 source_type 调用 fetcher
  -> fetcher 返回 RawItem / PaperCandidate
  -> parser / normalizer 生成 Paper
  -> duplicate_filter 合并或更新
  -> keyword_filter / scoring 计算分数
  -> repository 写入 SQLite
  -> report renderer 输出 Markdown / JSON
  -> 可选 output 发送通知
```

### 4.2 模块边界

建议目录：

```text
paper_watcher/
  pyproject.toml
  README.md
  .env.example
  Dockerfile
  docker-compose.yml
  config/
    sources.yaml
    venues.yaml
    keywords.yaml
    scoring.yaml
    report.yaml
    settings.yaml
  paper_watcher/
    main.py
    models.py
    settings.py
    config_loader.py
    fetchers/
    parsers/
    filters/
    storage/
    reports/
    llm/
    outputs/
  tests/
```

与旧计划相比，新增 `config_loader.py` 和 `venues.yaml`，并把“监控哪些源”彻底从程序包中拿出来。

### 4.3 Fetcher 插件接口

每个 fetcher 实现同一个接口：

```python
class Fetcher(Protocol):
    source_type: str

    def fetch(self, source: Source, context: FetchContext) -> FetchResult:
        ...
```

`FetchResult` 应包含：

```text
source_id
fetched_count
items
etag / last_modified / content_hash 等状态更新
errors
raw_debug_info
```

Fetcher 只负责“从某类来源拿到候选条目”，不负责最终评分、不负责报告、不直接操作数据库。

### 4.4 Parser / Normalizer

Parser 负责从不同来源格式中提取字段：

```text
title
authors
abstract
venue
paper_url
pdf_url
doi
published_at
source_url
raw_json
```

Normalizer 负责：

```text
标题规范化
作者规范化
URL 规范化
venue alias 归一化
年份推断
arXiv ID / DOI / DBLP key 提取
```

Parser 不应该知道某个会议是不是 CCF A。这个信息来自 `Source` 或 `venues.yaml`。

### 4.5 Storage

SQLite 第一版足够。

表：

```text
sources
papers
scan_runs
paper_source_seen
source_state
```

建议在原计划三张表基础上新增两张：

`paper_source_seen` 用于记录同一论文被哪些源发现，解决 arXiv、DBLP、官网、OpenReview 多来源合并问题。

```sql
CREATE TABLE paper_source_seen (
    paper_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_item_id TEXT,
    source_url TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    raw_json TEXT,
    PRIMARY KEY (paper_id, source_id, source_item_id)
);
```

`source_state` 用于保存不同 source_type 的增量状态，避免把太多状态塞进 `sources.metadata_json`。

```sql
CREATE TABLE source_state (
    source_id TEXT PRIMARY KEY,
    last_success_at TEXT,
    last_error_at TEXT,
    last_error TEXT,
    etag TEXT,
    last_modified TEXT,
    content_hash TEXT,
    last_changed_at TEXT,
    cursor TEXT,
    metadata_json TEXT
);
```

---

## 5. 第一版最小可运行范围

第一版目标不是覆盖所有清单，而是跑通端到端闭环。

必须实现：

```text
配置加载与校验
SQLite 初始化
RSSFetcher
基础 DBLPFetcher
WebsiteWatcher 的 hash 变化检测
Paper 数据模型
Source 数据模型
标题规范化
基础去重
关键词评分
Markdown 单次扫描报告
CLI
基础测试
```

第一版可以暂缓：

```text
OpenReviewFetcher 的复杂 accepted decision 解析
Semantic Scholar
Email import
SearchFallback
LLM 摘要
AstrBot 插件
复杂 fuzzy matching
网页论文列表通用解析
```

第一版 WebsiteWatcher 的最低要求：

1. 抓取页面。
2. 用 CSS selector 提取正文。
3. 计算 hash。
4. hash 变化时记录变化事件。
5. 不强行把任意网页变化解析为论文。

这样可以避免把网页解析做得过早、过脆。

---

## 6. CLI 设计

建议使用 Typer。

第一阶段命令：

```bash
paperwatcher init-db
paperwatcher validate-config
paperwatcher verify-sources
paperwatcher scan --once
paperwatcher scan --source arxiv_cs_cr
paperwatcher report --latest
paperwatcher list --recommendation read
paperwatcher search "prompt injection"
paperwatcher export --format json
```

命令职责：

`init-db`：创建或迁移 SQLite 表。  
`validate-config`：只校验 YAML 和模型，不联网。  
`verify-sources`：联网测试源可用性，更新 source 状态。  
`scan`：抓取、去重、评分、入库、生成报告。  
`report`：基于数据库重新生成报告。  
`list`：查询本地论文库。  
`search`：本地关键词搜索。  
`export`：导出 JSON，供 AstrBot 或其他系统消费。

---

## 7. 开发计划

### 阶段 0：项目骨架与配置契约

目标：建立可维护的项目结构，先固定边界。

交付：

```text
pyproject.toml
README.md
.env.example
config/*.yaml 示例
paper_watcher/models.py
paper_watcher/config_loader.py
paper_watcher/main.py
tests/test_config_loader.py
```

验收标准：

```text
paperwatcher validate-config 能读取并校验所有配置
配置中新增 source 不需要改代码
非法 source_type、缺失 feed_url、无效 priority 能给出清晰错误
```

### 阶段 1：数据库与基础数据模型

目标：把扫描状态、论文、来源状态持久化。

交付：

```text
storage/database.py
storage/migrations.py
storage/repository.py
SQLite schema
init-db CLI
tests/test_repository.py
```

验收标准：

```text
init-db 可重复执行
Paper 可插入、更新、查询
SourceState 可更新 ETag / Last-Modified / content_hash
scan_runs 能记录成功和失败
```

### 阶段 2：RSS 端到端扫描

目标：先用 arXiv RSS 或任意 RSS 源跑通完整流程。

交付：

```text
fetchers/base.py
fetchers/rss_fetcher.py
parsers/rss_parser.py
parsers/normalizer.py
filters/duplicate_filter.py
filters/keyword_filter.py
filters/scoring.py
reports/markdown_report.py
scan --once CLI
```

验收标准：

```text
可扫描 sources.yaml 中所有启用 RSS 源
支持超时、重试、错误记录
重复运行不会重复插入同一论文
生成 reports/run_YYYY-MM-DD_HH-mm.md
报告按 read / skim / archive 分组
```

### 阶段 3：DBLP 兜底源

目标：支持正式出版记录扫描和元数据补全。

交付：

```text
fetchers/dblp_fetcher.py
parsers/dblp_parser.py
venue_key 配置校验
DBLP key 去重
```

验收标准：

```text
可通过 venue_key 扫描目标 venue
能提取 title、authors、year、venue、doi/url
DBLP 记录能与已有 arXiv/RSS 记录合并或建立关联
```

### 阶段 4：网页变化监控

目标：支持会议 accepted papers / program 页面变化监控。

交付：

```text
fetchers/website_fetcher.py
content hash 状态保存
raw html snapshot 可选保存
网页变化事件入报告
```

验收标准：

```text
watch_url + css_selector 可配置
页面无变化时不重复报告
页面变化时能在报告中列出变化源
抓取失败只记录错误，不生成假论文
```

### 阶段 5：OpenReview

目标：支持 ICLR、ICML、NeurIPS 等 OpenReview 来源。

交付：

```text
fetchers/openreview_fetcher.py
openreview_venue_id 配置
decision 过滤配置
openreview_id 去重
```

验收标准：

```text
venue id 不硬编码
能按配置筛选 accepted / oral / spotlight
能提取 title、authors、abstract、pdf、keywords
不访问需要登录的私有数据
```

### 阶段 6：报告与本地检索增强

目标：让系统输出真正可读、可查询。

交付：

```text
weekly report
source statistics
failed source section
list CLI
search CLI
json export
```

验收标准：

```text
可生成每日/每周报告
报告包含新增数量、高相关数量、失败源
可按 recommendation、source、关键词查询
JSON 可被后续 AstrBot 插件读取
```

### 阶段 7：LLM 摘要

目标：只对高价值论文做低成本摘要和相关性判断。

交付：

```text
llm/client.py
llm/summarizer.py
llm/prompts.py
摘要缓存
失败降级
```

验收标准：

```text
只对 score >= min_score 且有 abstract 的论文调用 LLM
每次运行最多摘要 N 篇
LLM 失败不影响扫描和报告
同一论文不重复计费摘要
```

### 阶段 8：部署与通知层

目标：稳定部署到云服务器，并为 AstrBot 留接口。

交付：

```text
Dockerfile
docker-compose.yml
定时任务方案
logs 目录
备份说明
outputs/webhook_output.py
AstrBot JSON 消费接口说明
```

验收标准：

```text
Docker Compose 可启动
配置、数据、报告、日志通过 volume 挂载
服务可定时运行
AstrBot 不依赖 PaperWatcher 内部代码，只读取报告或 JSON
```

---

## 8. 推荐实施顺序

实际开发按以下顺序推进：

1. 新建项目骨架。
2. 实现 Pydantic 配置模型和 `validate-config`。
3. 实现 SQLite schema 和 `init-db`。
4. 实现 RSS 扫描闭环。
5. 加入去重、关键词评分、Markdown 报告。
6. 加入 DBLP。
7. 加入 WebsiteWatcher。
8. 加入 OpenReview。
9. 扩展周报、查询、JSON export。
10. 最后接 LLM 摘要和通知层。

每一步都要保持命令可运行、测试可执行、配置可替换。

---

## 9. 质量要求

### 9.1 配置质量

```text
所有 YAML 必须有 schema 校验
所有 source 必须有唯一 id
所有 source_type 必须有对应 fetcher 或明确标记 unsupported
priority 必须在 1-5
status 必须是 verified / needs_verification / deprecated
enabled=false 的源不参与扫描
```

### 9.2 抓取质量

```text
所有网络请求必须有 timeout
所有 fetcher 必须记录错误，不允许异常直接中断整个扫描
RSS 支持 ETag / Last-Modified
网页监控保存 content_hash
失败源进入报告
```

### 9.3 数据质量

```text
title 不能为空
normalized_title 必须生成
first_seen_at 只在首次插入时设置
last_seen_at 每次再次发现时更新
raw_json 尽量保存原始字段
多来源发现同一论文时保留 source seen 记录
```

### 9.4 测试要求

最低测试覆盖：

```text
配置加载和校验
标题规范化
关键词评分
推荐等级计算
去重规则
SQLite repository
RSS item 解析
报告渲染
```

---

## 10. 与现有文档的关系

已有文档分工如下：

```text
paper_sources_monitoring_catalog.md
  负责回答：值得监控哪些期刊、会议、来源？

paper_watcher_development_plan.md
  负责回答：PaperWatcher 最初设想有哪些模块？

paper_watcher_architecture_and_development_plan.md
  负责回答：程序与监控内容如何解耦？按什么阶段开发？
```

后续开发应以本文档作为架构边界依据，以 `paper_sources_monitoring_catalog.md` 作为配置内容来源。

当新增会议或期刊时，优先修改：

```text
config/sources.yaml
config/venues.yaml
```

只有当出现新的来源类型或新的处理能力时，才修改程序代码。


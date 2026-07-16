# PaperWatcher 开发计划

生成日期：2026-07-08  
用途：交给 Codex 作为开发任务说明。  
项目目标：在云服务器上运行一个论文追踪程序，自动接收、过滤、整理网络流量安全 × AI 安全 × 反诈智能体相关的最新论文，并生成可读简报；后续可接 AstrBot 做定时播报。

---

## 1. 项目定位

PaperWatcher 不是普通 RSS 阅读器，而是一个面向个人研究方向的“论文情报过滤器”。

目标是把以下来源统一处理：

```text
arXiv RSS / API
CCF A/B 期刊 TOC RSS / Alert
CCF A/B 会议 accepted papers / program / proceedings
DBLP venue metadata
OpenReview accepted papers
Semantic Scholar topic / author / citation alerts
会议官网网页变化监控
```

输出：

```text
每次运行后的增量论文列表
每日 / 每周 Markdown 简报
本地 SQLite 文献库
可选 LLM 摘要与相关性评分
后续 AstrBot / 邮件 / Telegram / 飞书推送
```

---

## 2. 推荐系统形态

采用“独立核心程序 + 可选 AstrBot 插件”的结构。

```text
PaperWatcher Core
  ├─ 抓取 RSS / API / 网页
  ├─ 解析论文元数据
  ├─ 去重
  ├─ CCF 白名单过滤
  ├─ 关键词过滤
  ├─ 相关性评分
  ├─ 可选 LLM 摘要
  ├─ SQLite 状态保存
  └─ Markdown / JSON 输出

AstrBot Plugin, 第二阶段
  ├─ /paper_today
  ├─ /paper_weekly
  ├─ /paper_search <keyword>
  └─ 定时播报最新 Markdown 简报
```

第一阶段不要把核心逻辑写成 AstrBot 插件。AstrBot 只作为通知层，核心程序应能独立运行、独立测试、独立部署。

---

## 3. 运行环境建议

目标环境：云服务器，Linux。  
推荐部署方式：Docker Compose。  
推荐语言：Python 3.11+。

### 3.1 基础依赖

```text
Python 3.11+
SQLite
feedparser
httpx
beautifulsoup4
lxml
pydantic
PyYAML
python-dateutil
APScheduler 或 cron
Jinja2
rich / typer, 可选
openai 或兼容 OpenAI API 的 SDK, 可选
```

### 3.2 部署目录

```text
/opt/paper-watcher/
  ├─ app/
  ├─ config/
  ├─ data/
  ├─ reports/
  ├─ logs/
  ├─ .env
  ├─ docker-compose.yml
  └─ README.md
```

### 3.3 权限建议

```text
运行用户：paperwatcher
不要使用 root 运行服务
.env 不进入 Git
SQLite 数据库定期备份
LLM API Key 只放在服务器环境变量或 .env
```

---

## 4. 项目目录设计

```text
paper_watcher/
  ├─ pyproject.toml
  ├─ README.md
  ├─ .env.example
  ├─ docker-compose.yml
  ├─ Dockerfile
  │
  ├─ config/
  │   ├─ sources.yaml
  │   ├─ ccf_whitelist.yaml
  │   ├─ keywords.yaml
  │   ├─ scoring.yaml
  │   └─ report.yaml
  │
  ├─ paper_watcher/
  │   ├─ __init__.py
  │   ├─ main.py
  │   ├─ models.py
  │   ├─ settings.py
  │   │
  │   ├─ fetchers/
  │   │   ├─ base.py
  │   │   ├─ rss_fetcher.py
  │   │   ├─ arxiv_fetcher.py
  │   │   ├─ dblp_fetcher.py
  │   │   ├─ openreview_fetcher.py
  │   │   ├─ website_fetcher.py
  │   │   └─ semantic_scholar_fetcher.py
  │   │
  │   ├─ parsers/
  │   │   ├─ paper_parser.py
  │   │   ├─ html_parser.py
  │   │   └─ normalizer.py
  │   │
  │   ├─ filters/
  │   │   ├─ ccf_filter.py
  │   │   ├─ keyword_filter.py
  │   │   ├─ duplicate_filter.py
  │   │   └─ scoring.py
  │   │
  │   ├─ llm/
  │   │   ├─ summarizer.py
  │   │   ├─ prompts.py
  │   │   └─ client.py
  │   │
  │   ├─ storage/
  │   │   ├─ database.py
  │   │   ├─ migrations.py
  │   │   └─ repository.py
  │   │
  │   ├─ reports/
  │   │   ├─ markdown_report.py
  │   │   ├─ json_export.py
  │   │   └─ templates/
  │   │       └─ weekly_report.md.j2
  │   │
  │   └─ outputs/
  │       ├─ file_output.py
  │       ├─ email_output.py
  │       └─ webhook_output.py
  │
  ├─ scripts/
  │   ├─ run_once.py
  │   ├─ run_daily.py
  │   ├─ run_weekly.py
  │   └─ init_db.py
  │
  └─ tests/
      ├─ test_dedup.py
      ├─ test_keyword_filter.py
      ├─ test_scoring.py
      └─ test_report_render.py
```

---

## 5. 核心数据模型

### 5.1 Paper

```python
class Paper(BaseModel):
    id: str | None = None
    title: str
    normalized_title: str
    authors: list[str] = []
    abstract: str | None = None
    venue: str | None = None
    venue_type: Literal["journal", "conference", "preprint", "unknown"] = "unknown"
    ccf_level: Literal["A", "B", "C", "non_ccf", "unknown"] = "unknown"
    area: str | None = None
    source_id: str
    source_url: str | None = None
    paper_url: str | None = None
    pdf_url: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    dblp_key: str | None = None
    openreview_id: str | None = None
    year: int | None = None
    published_at: datetime | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    score: float = 0.0
    tags: list[str] = []
    summary: str | None = None
    recommendation: Literal["read", "skim", "archive", "ignore"] = "archive"
```

### 5.2 Source

```python
class Source(BaseModel):
    id: str
    name: str
    source_type: Literal[
        "rss",
        "arxiv",
        "dblp",
        "openreview",
        "website_watch",
        "semantic_scholar",
        "email_import"
    ]
    url: str | None = None
    feed_url: str | None = None
    venue_key: str | None = None
    openreview_venue_id: str | None = None
    ccf_level: str = "unknown"
    area: str | None = None
    priority: int = 3
    enabled: bool = True
    status: Literal["verified", "needs_verification", "deprecated"] = "needs_verification"
```

---

## 6. 数据库设计

使用 SQLite。第一版不需要 PostgreSQL。

### 6.1 表结构

```sql
CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    url TEXT,
    feed_url TEXT,
    ccf_level TEXT,
    area TEXT,
    priority INTEGER,
    enabled INTEGER DEFAULT 1,
    status TEXT,
    last_success_at TEXT,
    last_error_at TEXT,
    last_error TEXT,
    metadata_json TEXT
);

CREATE TABLE papers (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    authors_json TEXT,
    abstract TEXT,
    venue TEXT,
    venue_type TEXT,
    ccf_level TEXT,
    area TEXT,
    source_id TEXT,
    source_url TEXT,
    paper_url TEXT,
    pdf_url TEXT,
    doi TEXT,
    arxiv_id TEXT,
    dblp_key TEXT,
    openreview_id TEXT,
    year INTEGER,
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    score REAL DEFAULT 0,
    tags_json TEXT,
    summary TEXT,
    recommendation TEXT,
    raw_json TEXT
);

CREATE TABLE scan_runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT,
    source_id TEXT,
    fetched_count INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    updated_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    log TEXT
);
```

### 6.2 去重规则

按强到弱：

```text
1. DOI 完全相同
2. arXiv ID 完全相同
3. DBLP key 完全相同
4. OpenReview ID 完全相同
5. normalized_title + first_author + year 相同
6. title fuzzy match > 0.95 且作者高度重合
```

---

## 7. 抓取模块设计

### 7.1 RSSFetcher

负责：arXiv RSS、ACM DL RSS、IEEE RSS、Springer/Wiley RSS 等。

要求：

```text
- 支持 ETag / Last-Modified
- 支持超时和重试
- 支持 feed 无效时记录 error
- 输出统一 Paper 对象
- 原始 feed item 存入 raw_json
```

### 7.2 DBLPFetcher

负责：正式索引兜底。

要求：

```text
- 支持 venue key 扫描
- 支持按年份过滤
- 支持增量更新
- 能补全 DOI / URL / authors / venue / year
```

第一版可以先解析 DBLP JSON/XML 或 HTML 页面，优先选择 API。

### 7.3 OpenReviewFetcher

负责：ICML、NeurIPS、ICLR、UAI 等。

要求：

```text
- venue id 不硬编码，写在 config
- 支持按 decision / accepted 过滤
- 支持提取 title / authors / abstract / pdf / keywords
- 不抓取私有或需要登录权限的数据
```

### 7.4 WebsiteWatcher

负责：会议 accepted papers / program 页面。

要求：

```text
- 支持 URL + CSS selector
- 保存正文 hash
- hash 变化时重新解析
- 解析失败时只生成网页变化提示，不要误判为新论文
- 对页面结构不稳定的会议保留 raw html snapshot
```

### 7.5 SearchFallback

第一版可不实现。第二阶段实现。

用途：

```text
定期搜索：<venue> <year> accepted papers
发现候选 URL 后，人工或程序加入 website_watch
```

---

## 8. 过滤与评分模块

### 8.1 CCF 白名单过滤

规则：

```text
CCF A：基础分 +4
CCF B：基础分 +3
非 CCF 高价值源：基础分 +2
arXiv：基础分 0，但可因关键词加分
未知来源：默认不推送，只归档
```

### 8.2 关键词评分

示例：

```yaml
strong_keywords:
  encrypted traffic: 4
  traffic classification: 4
  network anomaly detection: 4
  intrusion detection: 4
  phishing detection: 4
  fraud detection: 5
  scam detection: 5
  LLM security: 5
  prompt injection: 5
  jailbreak: 4
  agent security: 5
  Android security: 4

medium_keywords:
  adversarial attack: 2
  robustness: 2
  privacy: 2
  federated learning: 2
  time series classification: 3
  behavior modeling: 3
  causal reasoning: 3
  RAG: 3
```

### 8.3 推荐等级

```text
score >= 9：read，建议精读
score >= 6：skim，建议略读
score >= 3：archive，归档不推送
score < 3：ignore，不进入简报
```

### 8.4 LLM 摘要触发条件

不要对所有论文调用 LLM。

```text
只对 score >= 6 的论文摘要
只对有 abstract 的论文摘要
每天最多摘要 N 篇，默认 20
失败时不阻塞主流程
LLM 结果缓存，避免重复计费
```

---

## 9. LLM 摘要格式

Prompt 目标：不是泛泛总结，而是判断是否对用户课题有用。

输出格式：

```markdown
### {{ title }}

- 来源：{{ venue }} / {{ source }}
- CCF：{{ ccf_level }}
- 相关性：高 / 中 / 低
- 一句话总结：
- 方法要点：
- 与我的研究方向的关系：
- 可借鉴位置：
  - 第一层：流式证据收集 / 高敏探头
  - 第二层：风险模式判别 / 阶段识别 / 交互状态识别
  - 第三层：云端知识增强 / 困难案例上行
- 是否建议精读：是 / 否
```

要求：

```text
- 不要编造论文未出现的方法
- 如果只有标题没有摘要，只做“标题级判断”
- 明确标记不确定性
- 重点提取可借鉴方法，而不是写普通科普摘要
```

---

## 10. 报告输出

### 10.1 每次运行报告

文件名：

```text
reports/run_YYYY-MM-DD_HH-mm.md
```

内容：

```markdown
# PaperWatcher 本次扫描报告

扫描时间：
扫描源数量：
新增论文数量：
高相关论文数量：
抓取失败源：

## 强相关，建议精读

## 中等相关，可略读

## 仅归档

## 抓取错误
```

### 10.2 每周报告

文件名：

```text
reports/weekly_YYYY-WW.md
```

内容：

```markdown
# 本周论文追踪简报

时间范围：
关注方向：网络流量安全、AI 安全、反诈智能体、异常检测

## 一、强相关论文，建议精读

## 二、中等相关论文，可略读

## 三、低相关或仅归档

## 四、本周来源统计

| 来源 | 新增 | 强相关 | 错误 |
|---|---:|---:|---:|

## 五、下周需要人工检查的会议页面
```

---

## 11. CLI 设计

使用 Typer 或 argparse。

```bash
paperwatcher init-db
paperwatcher verify-sources
paperwatcher scan --once
paperwatcher scan --source arxiv_cs_cr
paperwatcher report --daily
paperwatcher report --weekly
paperwatcher list --recommendation read
paperwatcher search "prompt injection"
paperwatcher export --format json
```

---

## 12. Docker 部署

### 12.1 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY paper_watcher ./paper_watcher
COPY config ./config
COPY scripts ./scripts

RUN pip install --no-cache-dir .

CMD ["paperwatcher", "scan", "--once"]
```

### 12.2 docker-compose.yml

```yaml
services:
  paperwatcher:
    build: .
    container_name: paperwatcher
    env_file: .env
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./reports:/app/reports
      - ./logs:/app/logs
    restart: unless-stopped
```

第一版可以不常驻，只通过 cron 定时运行容器：

```bash
0 9 * * * cd /opt/paper-watcher && docker compose run --rm paperwatcher paperwatcher scan --once
0 10 * * 1 cd /opt/paper-watcher && docker compose run --rm paperwatcher paperwatcher report --weekly
```

---

## 13. AstrBot 插件，第二阶段

插件不要重复实现抓取逻辑，只调用 PaperWatcher Core 或读取报告文件。

### 13.1 命令

```text
/paper_today
/paper_weekly
/paper_search <keyword>
/paper_read <paper_id>
/paper_sources
```

### 13.2 插件逻辑

```text
/paper_weekly
  -> 调用 paperwatcher report --weekly 或读取最新 weekly report
  -> 如果报告过长，按章节分段发送
  -> 不在聊天消息里直接暴露 API Key、服务器路径等敏感信息
```

### 13.3 定时播报

建议定时任务仍由服务器 cron / systemd timer 负责，AstrBot 只负责发送。这样即使 AstrBot 重启，也不会影响抓取和数据库状态。

---

## 14. 开发里程碑

### Milestone 1：最小可用版本

目标：手动运行一次，生成 Markdown 报告。

任务：

```text
- 建立项目结构
- 实现 config 加载
- 实现 SQLite 初始化
- 实现 RSSFetcher
- 接入 arXiv RSS
- 实现关键词过滤和简单评分
- 实现 Markdown 报告
- 写基础测试
```

验收标准：

```text
运行 paperwatcher scan --once 后：
- 能抓取 arXiv cs.CR/cs.NI/cs.LG
- 能去重
- 能生成 reports/run_xxx.md
- 能把论文写入 data/papers.sqlite
```

---

### Milestone 2：CCF 期刊与 DBLP 兜底

任务：

```text
- 实现 CCF 白名单配置
- 实现 ACM/IEEE RSS 源接入
- 实现 DBLPFetcher
- 将 venue 与 ccf_level 关联
- 完善去重规则
```

验收标准：

```text
- 能扫描至少 10 个期刊源
- 能识别 CCF A/B 来源
- 同一论文不会因 arXiv + DBLP 重复出现在报告中
```

---

### Milestone 3：会议监控

任务：

```text
- 实现 WebsiteWatcher
- 支持 CSS selector / text hash
- 加入 USENIX Security、NDSS、S&P、SIGCOMM、IMC 等页面
- 页面变化时生成候选论文或变化提醒
```

验收标准：

```text
- 会议页面变化能被记录
- 解析失败时不产生错误论文
- 报告中能列出“需要人工检查的页面”
```

---

### Milestone 4：OpenReview 与 LLM 摘要

任务：

```text
- 实现 OpenReviewFetcher
- 接入 ICML / NeurIPS / ICLR
- 实现 LLM 摘要模块
- 增加摘要缓存
- 增加 LLM 调用限额
```

验收标准：

```text
- 只对 score >= 6 的论文摘要
- 摘要失败不影响报告生成
- 报告中包含“与用户课题关系”的字段
```

---

### Milestone 5：部署与自动运行

任务：

```text
- Dockerfile
- docker-compose.yml
- cron 或 systemd timer
- 日志轮转
- 数据库备份脚本
- README 部署说明
```

验收标准：

```text
- 服务器每天自动扫描
- 每周自动生成 weekly report
- 出错时 logs 中可定位问题
- 重启服务器后不会丢失状态
```

---

### Milestone 6：AstrBot 插件

任务：

```text
- 新建 astrbot_plugin_paperwatcher
- 支持读取 latest weekly report
- 支持 /paper_today /paper_weekly
- 支持长报告分段发送
- 可选支持命令触发 scan
```

验收标准：

```text
- AstrBot 可以发送最新报告
- 插件不保存核心状态
- 插件崩溃不影响 PaperWatcher Core
```

---

## 15. 错误处理要求

必须处理：

```text
RSS 源不可达
HTTP 403 / 429
网页结构变化
OpenReview venue id 失效
DBLP 返回空结果
LLM API 失败
摘要超时
SQLite 锁冲突
重复论文
标题缺失
摘要缺失
```

行为要求：

```text
- 单个源失败不影响其他源
- 每次 scan_runs 记录错误
- 错误进入报告的“抓取错误”部分
- 不因为 LLM 失败丢弃论文
```

---

## 16. 配置文件示例

### 16.1 sources.yaml

```yaml
sources:
  - id: arxiv_cs_cr
    name: arXiv cs.CR
    source_type: rss
    feed_url: https://rss.arxiv.org/rss/cs.CR
    ccf_level: non_ccf
    area: security
    priority: 5
    enabled: true

  - id: ieee_tdsc
    name: IEEE TDSC
    source_type: rss
    feed_url: null
    ccf_level: A
    area: security
    priority: 5
    enabled: true
    status: needs_verification

  - id: dblp_uss
    name: DBLP USENIX Security
    source_type: dblp
    venue_key: conf/uss
    ccf_level: A
    area: security
    priority: 5
    enabled: true

  - id: usenix_security_website
    name: USENIX Security Accepted Papers
    source_type: website_watch
    url: null
    ccf_level: A
    area: security
    priority: 5
    enabled: true
    status: needs_yearly_url
```

### 16.2 scoring.yaml

```yaml
base_score:
  A: 4
  B: 3
  non_ccf_high_value: 2
  non_ccf: 0
  unknown: -1

recommendation_thresholds:
  read: 9
  skim: 6
  archive: 3

llm_summary:
  enabled: true
  min_score: 6
  max_papers_per_run: 20
```

---

## 17. Codex 工作方式建议

1. 先建 Git 仓库。
2. 每个 milestone 单独一个 branch。
3. 每次开发先写测试，再实现。
4. 不要把 `.env`、API key、cookie、SSH key 提交。
5. 如果使用 Codex Remote SSH，只给普通用户权限，不给 root。
6. 每次修改部署配置前先生成 `git diff` 供人工检查。

---

## 18. 最终验收目标

项目完成后，应能做到：

```text
- 每天自动扫描 arXiv、RSS、DBLP、OpenReview、会议网页
- 每周生成 Markdown 简报
- 简报按“强相关 / 中等相关 / 仅归档”分类
- 每篇高相关论文有一句话总结和可借鉴点
- 所有论文持久化到 SQLite
- 同一论文不会重复推送
- 来源失效时不会中断整个系统
- 后续可以接 AstrBot 定时播报
```

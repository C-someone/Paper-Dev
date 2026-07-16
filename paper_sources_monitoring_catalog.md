# PaperWatcher 数据源监控清单：期刊与会议

生成日期：2026-07-08  
用途：交给 Codex 开发 `PaperWatcher` 时使用，作为需要监控的 CCF A/B 会议、期刊与补充来源清单。  
研究方向：网络流量安全、人工智能安全、LLM/Agent 安全、异常检测、反诈智能体、移动端安全。

---

## 0. 总原则

1. **CCF 2026 第七版推荐目录作为主白名单**。本清单优先覆盖：
   - 网络与信息安全
   - 计算机网络
   - 人工智能
   - 数据库 / 数据挖掘 / 内容检索
2. **不要假设所有会议都有 RSS**。会议通常需要组合使用：
   - accepted papers 页面监控
   - program 页面监控
   - proceedings 页面监控
   - DBLP venue 页面或 API
   - OpenReview API
   - 搜索引擎兜底
3. **期刊优先使用 TOC RSS / Early Access / Email Alert**。期刊比会议更适合 RSS 或出版社提醒。
4. **arXiv 只作为早期线索**，不作为高质量来源本身。arXiv 需要经过 CCF 白名单、关键词、LLM 评分过滤。
5. **每个来源都要持久化状态**，不要只记录最后扫描时间，还要记录 `paper_id / doi / title_hash / source_url / first_seen_at`，避免网页变更导致重复推送。

---

## 1. 可以 RSS / Atom 订阅的来源

这一类优先通过 `feedparser` 订阅。Codex 实现时要为每个 feed 做一次可用性测试，并把测试结果写入 `sources.yaml`。

### 1.1 arXiv 分类 RSS / Atom

| 来源 | 类型 | 订阅方式 | 建议优先级 | 说明 |
|---|---|---|---:|---|
| arXiv cs.CR | 预印本 | RSS / Atom | 5 | 安全、密码、系统安全、隐私 |
| arXiv cs.NI | 预印本 | RSS / Atom | 4 | 网络、流量、协议、测量 |
| arXiv cs.LG | 预印本 | RSS / Atom | 4 | 机器学习、异常检测、鲁棒性 |
| arXiv cs.AI | 预印本 | RSS / Atom | 3 | AI、Agent、推理 |
| arXiv cs.CL | 预印本 | RSS / Atom | 3 | LLM 安全、prompt injection、文本欺诈检测 |
| arXiv cs.SE | 预印本 | RSS / Atom | 2 | 软件安全、程序分析、Agent 工程相关 |

建议实现：

```yaml
- id: arxiv_cs_cr
  name: arXiv cs.CR
  source_type: rss
  url: https://rss.arxiv.org/rss/cs.CR
  category: preprint
  priority: 5
  ccf_level: non_ccf
```

---

### 1.2 ACM Digital Library：TOC RSS / Email Alert 优先

ACM DL 支持对具体出版物设置 Table of Contents RSS 或 Email Alert。对 ACM 期刊可以优先使用 RSS；对 ACM 会议，可以在正式 proceedings 进入 ACM DL 后使用 TOC RSS 或 DBLP 作为补充，但**accepted papers 阶段仍然需要会议官网监控**。

#### ACM 期刊

| 期刊 | 全称 | CCF | 领域 | 推荐订阅方式 | 优先级 |
|---|---|---|---|---|---:|
| TOPS | ACM Transactions on Privacy and Security | B | 网络与信息安全 | ACM DL TOC RSS / Email | 5 |
| TOIT | ACM Transactions on Internet Technology | B | 计算机网络 | ACM DL TOC RSS / Email | 4 |
| TOSN | ACM Transactions on Sensor Networks | B | 计算机网络 | ACM DL TOC RSS / Email | 3 |
| TOIS | ACM Transactions on Information Systems | A | 数据库/数据挖掘/内容检索 | ACM DL TOC RSS / Email | 4 |
| TKDD | ACM Transactions on Knowledge Discovery from Data | B | 数据库/数据挖掘/内容检索 | ACM DL TOC RSS / Email | 5 |
| TWEB | ACM Transactions on the Web | B | 数据库/数据挖掘/内容检索 | ACM DL TOC RSS / Email | 4 |

#### ACM 会议的正式 proceedings 订阅

这些会议在正式出版后通常可通过 ACM DL / DBLP 追踪，但 accepted papers 阶段不要只依赖 RSS。

| 会议 | 全称 | CCF | 领域 | RSS 适用阶段 | 备注 |
|---|---|---|---|---|---|
| CCS | ACM Conference on Computer and Communications Security | A | 网络与信息安全 | proceedings 后 | accepted list 需官网监控 |
| SIGCOMM | ACM SIGCOMM Conference | A | 计算机网络 | proceedings 后 | accepted list 需官网监控 |
| MobiCom | ACM MobiCom | A | 计算机网络 | proceedings 后 | 移动网络与移动安全 |
| CoNEXT | ACM CoNEXT | B | 计算机网络 | proceedings 后 | 网络系统 |
| MobiSys | ACM MobiSys | B | 计算机网络 | proceedings 后 | 移动系统、端侧系统 |
| IMC | ACM Internet Measurement Conference | B | 计算机网络 | proceedings 后 | 网络测量、流量分析，强相关 |
| SIGKDD / KDD | ACM SIGKDD Conference | A | 数据挖掘 | proceedings 后 | fraud/anomaly/graph mining |
| SIGIR | ACM SIGIR | A | 信息检索 | proceedings 后 | RAG、检索安全相关 |
| CIKM | ACM CIKM | B | 数据挖掘/检索 | proceedings 后 | 知识、检索、Web |
| WSDM | ACM WSDM | B | 数据挖掘/检索 | proceedings 后 | Web 数据挖掘 |

---

### 1.3 IEEE Xplore：期刊 RSS / TOC Alert 优先

IEEE Xplore 通常支持期刊和 magazine 的 Email Alert / RSS Feed。对于 IEEE 会议，正式收录后可用 IEEE Xplore Alert / DBLP 追踪；accepted papers 阶段仍要官网监控。

#### IEEE / IEEE-ACM 期刊

| 期刊 | 全称 | CCF | 领域 | 推荐订阅方式 | 优先级 |
|---|---|---|---|---|---:|
| TDSC | IEEE Transactions on Dependable and Secure Computing | A | 网络与信息安全 | IEEE Xplore RSS / Alert | 5 |
| TIFS | IEEE Transactions on Information Forensics and Security | A | 网络与信息安全 | IEEE Xplore RSS / Alert | 5 |
| JSAC | IEEE Journal on Selected Areas in Communications | A | 计算机网络 | IEEE Xplore RSS / Alert | 4 |
| TMC | IEEE Transactions on Mobile Computing | A | 计算机网络 | IEEE Xplore RSS / Alert | 5 |
| TON | IEEE/ACM Transactions on Networking | A | 计算机网络 | IEEE Xplore / ACM / DBLP | 5 |
| TCOM | IEEE Transactions on Communications | B | 计算机网络 | IEEE Xplore RSS / Alert | 2 |
| TWC | IEEE Transactions on Wireless Communications | B | 计算机网络 | IEEE Xplore RSS / Alert | 2 |
| TKDE | IEEE Transactions on Knowledge and Data Engineering | A | 数据挖掘 | IEEE Xplore RSS / Alert | 5 |
| TPAMI | IEEE TPAMI | A | 人工智能 | IEEE Xplore RSS / Alert | 3 |
| TNNLS | IEEE Transactions on Neural Networks and Learning Systems | B | 人工智能 | IEEE Xplore RSS / Alert | 5 |
| TAC | IEEE Transactions on Affective Computing | B | 人工智能 | IEEE Xplore RSS / Alert | 3 |
| TASLP | IEEE/ACM Transactions on Audio, Speech and Language Processing | B | 人工智能/NLP | IEEE Xplore RSS / Alert | 3 |

#### IEEE 会议的正式索引追踪

| 会议 | 全称 | CCF | 领域 | 自动方式 | 备注 |
|---|---|---|---|---|---|
| IEEE S&P | IEEE Symposium on Security and Privacy | A | 网络与信息安全 | IEEE Xplore / DBLP / 官网监控 | accepted list 需官网 |
| ACSAC | Annual Computer Security Applications Conference | B | 网络与信息安全 | IEEE/ACM/DBLP + 官网 | 应用安全 |
| DSN | Dependable Systems and Networks | B | 网络与信息安全 | IEEE / DBLP + 官网 | 可靠系统与安全 |
| INFOCOM | IEEE INFOCOM | A | 计算机网络 | IEEE Xplore / DBLP / 官网 | 网络通信 |
| ICNP | IEEE International Conference on Network Protocols | B | 计算机网络 | IEEE Xplore / DBLP / 官网 | 协议与网络安全 |
| ICDM | IEEE International Conference on Data Mining | B | 数据挖掘 | IEEE Xplore / DBLP / 官网 | 异常检测、数据挖掘 |

---

### 1.4 可能可 RSS 的其他期刊平台

这些平台通常能通过期刊页面 RSS、出版社提醒或 DBLP 追踪，但不同期刊的 feed 位置不完全一致，Codex 需要实际验证。

| 期刊 | 出版方 | CCF | 领域 | 建议方式 | 优先级 |
|---|---|---|---|---|---:|
| Journal of Cryptology | Springer | A | 网络与信息安全 | Springer RSS / DBLP | 1 |
| IJCV | Springer | A | 人工智能 | Springer RSS / DBLP | 2 |
| AAMAS | Springer | B | 人工智能 | Springer RSS / DBLP | 4 |
| Machine Learning | Springer | B | 人工智能 | Springer RSS / DBLP | 4 |
| DMKD | Springer | B | 数据挖掘 | Springer RSS / DBLP | 5 |
| KAIS | Springer | B | 数据挖掘 | Springer RSS / DBLP | 4 |
| JASIST | Wiley | B | 数据挖掘/信息科学 | Wiley RSS / DBLP | 2 |

---

## 2. 可以通过其他方法自动订阅 / 监控的来源

这一类不一定有稳定 RSS，但可以通过 API、Email Alert、DBLP、OpenReview、Semantic Scholar 或网页变化监控自动化。

### 2.1 OpenReview API

适用：使用 OpenReview 的会议。OpenReview 更适合 API，而不是传统 RSS。

| 会议 | CCF | 领域 | 自动方法 | 说明 |
|---|---|---|---|---|
| ICML | A | 人工智能 | OpenReview API + DBLP | 关注 accepted papers、oral/spotlight、topic |
| NeurIPS | A | 人工智能 | OpenReview API + DBLP + 官网 | AI safety / LLM safety 重点源 |
| ICLR | 非 CCF 补充源 | 人工智能 | OpenReview API | AI safety 很重要，建议保留但单独标记 `non_ccf_high_value` |
| COLT | B | 人工智能 | OpenReview/官网/DBLP | 理论 ML，相关性较低 |
| UAI | B | 人工智能 | OpenReview/官网/DBLP | 不确定性、因果、鲁棒推理 |

建议实现：

```yaml
- id: openreview_icml
  name: ICML OpenReview
  source_type: openreview
  venue_hint: ICML.cc/2026/Conference
  ccf_level: A
  category: ai
  priority: 5
  status: needs_yearly_venue_id
```

注意：OpenReview venue id 每年可能不同，不应硬编码；需要支持从配置中更新。

---

### 2.2 ScienceDirect / Elsevier：Search Alert / Volume-Issue Alert

Elsevier 期刊更建议走 ScienceDirect Alert，而不是假设都有 RSS。对于程序端，优先方案是：

1. 由用户在 ScienceDirect 上配置 Search Alert / Journal Alert。
2. 系统从邮件、RSS 替代源、DBLP 或网页页面抓取结果。
3. 对于抓取困难的期刊，用 DBLP API 做正式索引兜底。

| 期刊 | 出版方 | CCF | 领域 | 建议方法 | 优先级 |
|---|---|---|---|---|---:|
| Computers & Security | Elsevier | B | 网络与信息安全 | ScienceDirect Alert + DBLP | 5 |
| Computer Networks | Elsevier | B | 计算机网络 | ScienceDirect Alert + DBLP | 4 |
| Artificial Intelligence | Elsevier | A | 人工智能 | ScienceDirect Alert + DBLP | 3 |
| Neural Networks | Elsevier | B | 人工智能 | ScienceDirect Alert + DBLP | 4 |
| Information Processing & Management | Elsevier | B | 数据挖掘/检索 | ScienceDirect Alert + DBLP | 4 |
| Information Sciences | Elsevier | B | 数据挖掘/AI | ScienceDirect Alert + DBLP | 4 |
| Data & Knowledge Engineering | Elsevier | B | 数据挖掘/AI | ScienceDirect Alert + DBLP | 2 |
| Journal of Web Semantics | Elsevier | B | 数据挖掘/Web | ScienceDirect Alert + DBLP | 2 |

---

### 2.3 DBLP Venue API / 页面兜底

DBLP 是所有正式发表版本的兜底源。缺点是 DBLP 可能比 accepted papers 页面晚；优点是稳定、结构化、适合去重。

建议用途：

| 用途 | 说明 |
|---|---|
| venue 正式索引 | 每周扫描目标 venue 的 DBLP 页面或 API |
| 去重辅助 | 用 title、authors、year、venue 匹配 arXiv / proceedings |
| 补全元数据 | DOI、URL、pages、publisher |
| 稳定归档 | 作为最终 bibliographic record |

必须实现：

```yaml
source_type: dblp
fields:
  - venue_key
  - ccf_level
  - area
  - priority
  - last_seen_dblp_key
```

---

### 2.4 Semantic Scholar Alerts / API

Semantic Scholar 更适合追踪：

| 场景 | 用法 |
|---|---|
| 固定作者 | 创建 author alert |
| 固定主题 | 创建 topic alert / research feed |
| 引文更新 | 对核心论文设置 citation alert |
| 元数据补全 | 用 API 补 abstract、citation count、fields of study |

建议不要把 Semantic Scholar 作为主数据源，而是作为补充评分信号。

---

### 2.5 需要网页变化监控，但可以自动化的会议

这些会议通常每年有 accepted papers / program / technical sessions 页面，但 URL、发布时间和页面结构可能变动。Codex 应实现 `website_watch` 类型：保存 URL、CSS selector、正文 hash、最后更新时间、失败次数。

| 会议 | CCF | 领域 | 建议监控页面 | 优先级 | 备注 |
|---|---|---|---|---:|---|
| USENIX Security | A | 网络与信息安全 | accepted papers / technical sessions | 5 | 安全顶会，强相关 |
| NSDI | A | 计算机网络 | accepted papers / technical sessions | 4 | 网络系统 |
| NDSS | A | 网络与信息安全 | accepted papers / program | 5 | 网络安全强相关 |
| IEEE S&P | A | 网络与信息安全 | accepted papers / program | 5 | 安全顶会 |
| CCS | A | 网络与信息安全 | accepted papers / program | 5 | 后续可用 ACM DL/DBLP 兜底 |
| SIGCOMM | A | 计算机网络 | accepted papers / program | 5 | 流量、网络系统 |
| IMC | B | 计算机网络 | accepted papers / program | 5 | 网络测量、恶意行为分析 |
| RAID | B | 网络与信息安全 | accepted papers / program | 5 | 入侵检测强相关 |
| ACSAC | B | 网络与信息安全 | accepted papers / program | 4 | 应用安全 |
| ESORICS | B | 网络与信息安全 | accepted papers / program | 4 | 系统安全、隐私 |
| CoNEXT | B | 计算机网络 | accepted papers / program | 3 | 网络系统 |
| MobiSys | B | 计算机网络 | accepted papers / program | 4 | Android / 端侧系统相关 |
| ICNP | B | 计算机网络 | accepted papers / program | 3 | 协议安全 |
| AAAI | A | 人工智能 | accepted papers / proceedings | 3 | AI 应用与 Agent |
| IJCAI | A | 人工智能 | accepted papers / proceedings | 3 | AI 综合 |
| EMNLP | B | 人工智能/NLP | accepted papers / ACL Anthology | 4 | LLM 安全、文本欺诈 |
| CIKM | B | 数据挖掘/检索 | accepted papers / proceedings | 3 | RAG、知识增强 |
| WSDM | B | 数据挖掘/检索 | accepted papers / proceedings | 3 | Web 挖掘 |
| ICDM | B | 数据挖掘 | accepted papers / proceedings | 3 | 异常检测 |

---

## 3. 只能通过访问网站和搜索引擎检查的来源

这一类不是完全不能自动化，而是**不能稳定依赖 RSS/API**。实现上应做成低频任务：每周或每月运行一次搜索查询，发现新页面后加入 `website_watch`。

### 3.1 年度 URL 不固定的会议页面

| 会议 | CCF | 建议搜索 query | 检查频率 | 触发时间 |
|---|---|---|---|---|
| CCS | A | `CCS 2026 accepted papers` / `ACM CCS 2026 program` | 每周 | 录用通知前后到会议结束 |
| IEEE S&P | A | `IEEE S&P 2026 accepted papers` | 每周 | 分轮录用与会前 |
| NDSS | A | `NDSS 2026 accepted papers` | 每周 | 会前 2-4 个月 |
| USENIX Security | A | `USENIX Security 2026 accepted papers cycle` | 每周 | 各 cycle 公布后 |
| SIGCOMM | A | `SIGCOMM 2026 accepted papers` | 每周 | 录用通知后 |
| NSDI | A | `NSDI 2026 accepted papers technical sessions` | 每周 | 录用通知后 |
| IMC | B | `IMC 2026 accepted papers` | 每周 | 录用通知后 |
| RAID | B | `RAID 2026 accepted papers` | 每周 | 录用通知后 |
| ESORICS | B | `ESORICS 2026 accepted papers` | 每周 | 录用通知后 |
| ACSAC | B | `ACSAC 2026 accepted papers` | 每周 | 录用通知后 |
| KDD | A | `KDD 2026 accepted papers` / `SIGKDD 2026 research track accepted papers` | 每周 | 录用通知后 |
| AAAI | A | `AAAI 2027 accepted papers` | 每月/每周 | 录用通知后 |
| IJCAI | A | `IJCAI 2026 accepted papers` | 每周 | 录用通知后 |
| EMNLP | B | `EMNLP 2026 accepted papers findings main conference` | 每周 | 录用通知后 |

### 3.2 特殊补充源：非 CCF 但建议监控

这些不进入 CCF A/B 主评分，但对 AI 安全、LLM 安全、Agent 安全很重要。

| 来源 | 类型 | 监控方式 | 备注 |
|---|---|---|---|
| ICLR | 会议 | OpenReview API + 官网 | AI safety 高价值，标记 `non_ccf_high_value` |
| TMLR | 期刊/开放评审 | OpenReview API / 官网 | LLM/ML 安全可能出现 |
| arXiv cs.CR/cs.LG/cs.AI/cs.CL | 预印本 | RSS/Atom + 关键词过滤 | 噪声大，不能直接推送 |
| Papers with Code | 补充 | 搜索/网页监控 | 发现代码和 benchmark |
| GitHub trending / specific repos | 补充 | GitHub API | 只作为代码信号，不作为论文源 |

---

## 4. 推荐优先级

### 4.1 第一阶段必须实现的源

```text
arXiv: cs.CR, cs.NI, cs.LG, cs.AI, cs.CL
DBLP: 所有目标 venue 兜底
OpenReview: ICML, NeurIPS, ICLR
ACM DL RSS/TOC: TOPS, TOIT, TOIS, TKDD, TWEB, SIGCOMM/CCS/KDD proceedings
IEEE Xplore RSS/Alert: TDSC, TIFS, TMC, TON, TKDE, TNNLS
Website Watch: USENIX Security, NDSS, IEEE S&P, SIGCOMM, IMC, RAID
```

### 4.2 第二阶段再实现的源

```text
ScienceDirect Alerts: Computers & Security, Computer Networks, Information Sciences, IPM, Neural Networks
Springer RSS/DBLP: DMKD, KAIS, AAMAS, Machine Learning
Semantic Scholar Alerts/API
ACL Anthology / EMNLP / NAACL / ACL 相关页面
```

### 4.3 暂缓源

```text
偏理论密码会议：CRYPTO, EUROCRYPT, ASIACRYPT, TCC, PKC
偏通信理论期刊：TCOM, TWC
偏视觉期刊/会议：TPAMI, IJCV, CVPR, ICCV, ECCV
除非关键词命中 security / anomaly / fraud / attack / privacy / LLM safety，否则不推送。
```

---

## 5. 关键词过滤建议

### 5.1 强相关关键词

```text
encrypted traffic
traffic classification
network intrusion detection
network anomaly detection
malware detection
phishing detection
fraud detection
scam detection
telecom fraud
mobile security
Android security
LLM security
prompt injection
jailbreak
agent security
RAG security
multi-turn agent
streaming detection
early classification
```

### 5.2 中等相关关键词

```text
adversarial attack
robustness
privacy preservation
federated learning
time series classification
behavior modeling
user interaction
provenance
causal reasoning
knowledge-augmented detection
retrieval augmented generation
```

### 5.3 排除或降权关键词

```text
pure cryptography
homomorphic encryption only
wireless channel estimation
image segmentation only
speech recognition only
robot motion planning only
hardware accelerator only
```

---

## 6. Codex 实现注意事项

1. `sources.yaml` 中每个 source 必须有：
   - `id`
   - `name`
   - `source_type`: `rss | arxiv | dblp | openreview | website_watch | email_import | semantic_scholar`
   - `ccf_level`: `A | B | non_ccf | unknown`
   - `area`
   - `priority`
   - `status`: `verified | needs_verification | deprecated`
2. 对 RSS 源，记录：
   - `feed_url`
   - `last_etag`
   - `last_modified`
   - `last_success_at`
3. 对网页监控源，记录：
   - `watch_url`
   - `css_selector`
   - `content_hash`
   - `last_changed_at`
4. 对搜索兜底源，记录：
   - `query_template`
   - `year`
   - `last_checked_at`
   - `candidate_urls`
5. 所有论文必须进入统一模型：

```python
Paper(
    title: str,
    authors: list[str],
    abstract: str | None,
    venue: str | None,
    venue_type: str,   # journal / conference / preprint
    ccf_level: str,
    source: str,
    source_url: str,
    doi: str | None,
    arxiv_id: str | None,
    year: int | None,
    published_at: datetime | None,
    first_seen_at: datetime,
    score: float,
    tags: list[str],
)
```

---

## 7. 参考资料入口

- CCF 2026 第七版推荐目录：https://www.ccf.org.cn/Academic_Evaluation/By_category/
- CCF 网络与信息安全：https://www.ccf.org.cn/Academic_Evaluation/NIS/
- CCF 计算机网络：https://www.ccf.org.cn/Academic_Evaluation/CN/
- CCF 人工智能：https://www.ccf.org.cn/Academic_Evaluation/AI/
- CCF 数据库/数据挖掘/内容检索：https://www.ccf.org.cn/Academic_Evaluation/DM_CS/
- arXiv RSS Help：https://info.arxiv.org/help/rss.html
- arXiv API User Manual：https://info.arxiv.org/help/api/user-manual.html
- ACM DL Alerting Services：https://libraries.acm.org/training-resources/dl-alerting-services
- DBLP API FAQ：https://dblp.org/faq/How%2Bto%2Buse%2Bthe%2Bdblp%2Bsearch%2BAPI
- OpenReview API Docs：https://docs.openreview.net/
- Semantic Scholar Alerts FAQ：https://www.semanticscholar.org/faq/manage-alerts
- Zotero Feeds：https://www.zotero.org/support/feeds

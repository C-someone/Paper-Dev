# PaperWatcher / 文献与会议追踪系统

PaperWatcher 是一个面向用户订阅的文献与会议追踪系统。它的核心目标是长期监听论文、期刊、会议和会议页面更新，并让不同用户按自己的订阅范围读取新增内容。

PaperWatcher is a user-oriented literature and conference tracking system. Its core goal is to continuously monitor papers, journals, conferences, and conference pages, then let each user retrieve new items according to their own subscriptions.

## 运行逻辑 / Runtime Model

系统分为两个相互解耦的角色：

- 后台 worker：长期运行，监听已配置来源，将新增条目写入后端存储。
- 前台 service：等待外部激活。调用方以某个用户身份请求更新，前台返回该用户上次请求以来的新订阅内容。

The system is split into two decoupled roles:

- Background worker: runs continuously, watches configured sources, and writes newly discovered items into backend storage.
- Foreground service: waits for external activation. A caller asks as a given user, and the foreground returns new subscribed items since that user's previous request.

当前阶段外部调用方主要是人类通过 CLI 操作。后续 AstrBot 或其他自动化系统可以调用同一套前台逻辑。

At the current stage, the external caller is mainly a human using CLI commands. Later, AstrBot or another automation layer can call the same foreground logic.

```text
User library / 用户库
  -> user_id
  -> subscriptions
     -> rss subscriptions
     -> indexed venue subscriptions, later / 后续索引型 venue 订阅
     -> website-watch subscriptions, later / 后续网页监听订阅

Background worker / 后台
  -> runs for a long time / 长期运行
  -> scans RSS-like sources / 扫描 RSS 类来源
  -> periodically scans non-RSS sources, later / 后续定期扫描非 RSS 来源
  -> writes new items to backend storage / 写入后端存储
  -> current backend: files / 当前后端：文件
  -> later backend: SQLite/PostgreSQL behind the same interface / 后续可替换为数据库

Foreground service / 前台
  -> waits for external activation / 等待外部激活
  -> caller provides user_id / 调用方提供 user_id
  -> reads user subscriptions / 读取用户订阅
  -> finds new items since this user's last pull / 查询该用户上次拉取后的新增内容
  -> returns a compact answer / 返回紧凑结果
  -> current answer: paper title + link / 当前结果：标题 + 链接
  -> later answer: Markdown summary, LLM digest, AstrBot message / 后续：摘要、LLM digest、AstrBot 消息
```

当前事件流规则：

Current event-flow rule:

```text
后台扫描所有用户订阅 source_id 的并集。
The backend scans the union of all users' subscribed source IDs.

后台将发现的条目写入统一的全局事件流。
The backend writes discovered items to one global event stream.

前台按用户订阅和 cursor 从全局事件流中筛选。
The foreground filters the global event stream by each user's subscriptions and cursor.
```

详细设计见：

For the detailed design, see:

```text
docs/subscription_union_event_flow.md
```

## 当前范围 / Current Scope

当前阶段刻意保持系统小而可运行，优先验证订阅、扫描、记录、读取的完整闭环。

The current stage intentionally keeps the system small and runnable, focusing on a complete subscription, scan, record, and retrieval loop.

```text
已接入前后台流程的来源类型 / Implemented source types:
  RSS
  arXiv, as RSS-compatible record-only sources / arXiv，按 RSS 兼容的仅记录来源处理
  DBLP, as the first CCF-A/B venue source class / DBLP，作为第一批 CCF-A/B venue 来源

暂缓来源类型 / Deferred source types:
  OpenReview
  website_watch
  Semantic Scholar
  email_import
```

当前存储模式：

Current storage mode:

```text
File storage / 文件存储
```

文件存储层是临时实现，但业务逻辑应只通过较窄的接口访问它。这样后续替换为 SQLite 或 PostgreSQL 时，不需要大规模改动前后台流程。

The file storage layer is temporary, but business logic should access it through a narrow interface. This keeps the later migration to SQLite or PostgreSQL from forcing broad foreground/background changes.

在此基础上，项目提供一个可插拔的本地 SQLite 索引层：

On top of that, the project provides a pluggable local SQLite index layer:

```text
文件负责真相源。
Files remain the source of truth.

SQLite 只做镜像索引。
SQLite only mirrors the state as an index.

索引可以随时从文件重建。
The index can be rebuilt from files at any time.
```

这个索引不需要目标设备额外安装数据库服务；它使用 Python 自带的 `sqlite3`。

This index does not require an extra database service on the target machine; it uses Python's built-in `sqlite3`.

相关文档：

Related doc:

```text
docs/pluggable_sql_index_strategy.md
```

## 来源优先级策略 / Source Priority Policy

本项目的主要监听目标是 CCF-A/B 类期刊和会议。arXiv 作为低优先级早期信号源处理：

The main monitoring target is CCF-A/B journals and conferences. arXiv is treated as a low-priority early-signal source:

```text
arXiv 条目会被记录。
arXiv items are recorded.

arXiv 条目默认不推送给前台用户。
arXiv items are not pushed to foreground users by default.

arXiv 条目后续可用于检索、评分、分组和弱信号分析。
arXiv items can later be searched, scored, grouped, and used as weak signals.
```

当前 arXiv 来源配置：

Current arXiv source configuration:

```yaml
source_type: arxiv
priority: 1
notification_policy: record_only
```

TODO：后续根据论文发布者所属科研团队、机构、实验室、企业研究团队或安全厂商对 arXiv 记录进行分组。

TODO: group arXiv records by the submitting authors' research team, institution, lab, company research group, or security vendor when metadata is available.

监听清单热更新设计见：

For monitoring-list hot update design, see:

```text
docs/monitoring_hot_reload_design.md
```

对于没有稳定订阅渠道、年度 URL 经常变化的会议，项目提供会议页面发现流程：

For conferences without stable subscription channels and with changing yearly URLs, the project provides a conference-page discovery flow:

```bash
python3 -m paper_watcher.main discover-conferences --venue ndss --year 2027
python3 -m paper_watcher.main candidates list --status pending
python3 -m paper_watcher.main candidates approve --id cand_xxx --dry-run
```

候选来源先写入 `state/source_candidates.jsonl`，人工批准后再进入正式 `website_watch` 配置。

Candidates are first written to `state/source_candidates.jsonl`; after manual approval, they enter the formal `website_watch` configuration.

会议页面监控本身还有一层轻型智能体审查：

Conference page monitoring also has a lightweight agent review layer:

- 已知布局命中后，会先让智能体复核条目是否真的像论文或 program 记录。
- When a known layout matches, the agent first rechecks whether the extracted items really look like papers or program entries.
- 未知布局会先由智能体尝试分析页面结构并给出新 selector；如果仍然无法判断，系统只保留页面快照。
- Unknown layouts are first analyzed by the agent for a new selector set; if it still cannot decide, the system keeps only the page snapshot.

对于模糊搜索结果，可以用规则审核器或可选的 Pydantic AI reviewer 判断会议是否召开、关键日期是否可见、录用信息是否公开：

For fuzzy search results, use the rule-based reviewer or optional Pydantic AI reviewer to decide whether a conference is happening, whether key dates are visible, and whether accepted-paper information is public:

```bash
python3 -m paper_watcher.main review-search-results --input results.json --reviewer rule_based
python3 -m paper_watcher.main review-search-results --input results.json --reviewer pydantic_ai
python3 -m paper_watcher.main conference-reviews
```

如果配置了 `EXA_API_KEY`，也可以直接从会议 profile 发起低频搜索并审核：

If `EXA_API_KEY` is configured, the system can directly run low-frequency search from a venue profile and review the results:

```bash
python3 -m paper_watcher.main search-conference --venue ndss --year 2027 --num-results 2
python3 -m paper_watcher.main search-review-conference --venue ndss --year 2027 --reviewer pydantic_ai --dry-run --num-results 2
python3 -m paper_watcher.main review-conferences --year 2027 --reviewer auto --dry-run --num-results 2
```

`--dry-run` 不写入 `state/conference_search_reviews.jsonl`，适合调试。

`--dry-run` does not write `state/conference_search_reviews.jsonl`, which is useful for debugging.

高置信度且已公开录用信息的审核记录可以提升为候选监听源：

High-confidence reviews with public accepted-paper information can be promoted into source candidates:

```bash
python3 -m paper_watcher.main conference-reviews promote --venue ndss --year 2026 --dry-run
python3 -m paper_watcher.main conference-reviews promote --id review_xxx
python3 -m paper_watcher.main candidates list --status pending
python3 -m paper_watcher.main candidates approve --id cand_xxx --dry-run
```

promotion 只写入 `state/source_candidates.jsonl`，不会直接修改正式监听清单；正式加入 `config/sources.yaml` 仍需要 `candidates approve`。

Promotion only writes `state/source_candidates.jsonl`; it does not directly edit the formal monitoring list. Adding the source to `config/sources.yaml` still requires `candidates approve`.

Pydantic AI 是可选依赖；默认规则审核不需要模型 API。当前 DeepSeek 集成通过 Pydantic AI 的 OpenAI-compatible provider 调用模型，但使用纯 JSON 响应和本地 Pydantic 校验，避免依赖 provider-side tool 调用。

Pydantic AI is an optional dependency; the default rule-based reviewer does not require a model API. The current DeepSeek integration uses Pydantic AI's OpenAI-compatible provider, asks the model for plain JSON, and validates it locally with Pydantic to avoid provider-side tool calls.

相关环境变量：

Related environment variables:

```text
DEEPSEEK_API_KEY
DEEPSEEK_API_URL
DEEPSEEK_API_MODEL
EXA_API_KEY
EXA_API_URL
```

详细设计见：

For the detailed design, see:

```text
docs/conference_discovery_design.md
docs/pydantic_ai_search_review_design.md
```

## 用户库 / User Library

用户库位于：

The user library lives in:

```text
config/users.yaml
```

示例：

Example:

```yaml
users:
  - id: default
    display_name: Default User
    subscriptions:
      rss:
        - source_id: arxiv_cs_cr
        - source_id: arxiv_cs_lg
      indexed_venues: []
      website_watch: []
    delivery:
      format: text
      max_items: 20
```

RSS 订阅引用 `config/sources.yaml` 中定义的 source id。

RSS subscriptions refer to source IDs defined in `config/sources.yaml`.

后续索引型 venue 订阅可以记录额外字段，例如：

Future indexed venue subscriptions may store additional fields, for example:

```yaml
indexed_venues:
  - source_id: dblp_ccs
    venue_key: conf/ccs
    since_year: 2026
```

后续网页监听订阅可以记录页面 URL 和选择器，例如：

Future website-watch subscriptions may store page URLs and selectors, for example:

```yaml
website_watch:
  - source_id: usenix_security_2026_accepted
    watch_url: https://www.usenix.org/conference/usenixsecurity26/accepted-papers
    css_selector: main
```

这个区分很重要：程序不应强行把所有订阅类型压成同一种扁平结构。

This distinction matters: the program should not force all subscription types into one flat shape.

## 文件存储 / File Storage

当前文件后端位于：

The current file backend lives under:

```text
state/
```

主要状态文件：

Main state files:

```text
state/
  events.jsonl                  # append-only discovered-item events / 追加式发现事件
  source_state.json             # ETag / Last-Modified / cursor per source / 来源级扫描状态
  user_cursors.json             # last foreground pull timestamp/event per user / 用户前台读取 cursor
  source_verification.json      # source verification results / 来源验证结果
  config_reload_errors.jsonl    # hot-reload failures / 热更新失败日志
  source_candidates.jsonl       # conference website-watch candidates / 会议网页监听候选源
  conference_search_reviews.jsonl # fuzzy search review records / 模糊搜索审核记录
  scheduled_tasks.json          # low-frequency background task state / 低频后台任务状态
```

`events.jsonl` 是追加式事件流，每一行是一个 JSON 对象。

`events.jsonl` is append-only. Each line is one JSON object.

```json
{
  "event_id": "evt_...",
  "seen_at": "2026-07-15T00:00:00+00:00",
  "source_id": "arxiv_cs_cr",
  "source_type": "rss",
  "paper_id": "paper_...",
  "title": "Paper title",
  "link": "https://example.com/paper",
  "matched_users": []
}
```

`source_state.json` 存储来源级增量扫描状态。

`source_state.json` stores source-level incremental scan state.

```json
{
  "arxiv_cs_cr": {
    "etag": "...",
    "last_modified": "...",
    "last_success_at": "..."
  }
}
```

`user_cursors.json` 存储前台读取进度。

`user_cursors.json` stores foreground pull state.

```json
{
  "default": {
    "last_pulled_at": "2026-07-15T00:00:00+00:00"
  }
}
```

## 后台逻辑 / Background Worker

当前可用命令：

Available commands:

```text
paperwatcher background --once
paperwatcher background --loop --watch-config --interval 300
paperwatcher background --loop --enable-conference-review --conference-review-year 2026
paperwatcher background --loop --watch-config --enable-signal-review
```

`--once` 执行一次扫描。`--loop` 持续循环扫描直到被中断。配合 `--watch-config` 时，后台会在每轮扫描前检查 YAML 配置文件 fingerprint，并在配置有效时无重启热更新。

`--once` runs a single pass. `--loop` runs repeated passes until interrupted. With `--watch-config`, the worker checks YAML file fingerprints before each pass and reloads valid config changes without restarting.

会议搜索审核是低频后台任务，默认关闭。显式添加 `--enable-conference-review` 后，后台会按 `--conference-review-interval` 触发 `review-conferences` 批处理，调度状态写入 `state/scheduled_tasks.json`。

Conference search review is a low-frequency background task and is disabled by default. With `--enable-conference-review`, the background loop runs `review-conferences` according to `--conference-review-interval`, and task state is written to `state/scheduled_tasks.json`.

DBLP 会议卷/proceedings 等信号可以触发一次会议状态审核。启用 `--enable-signal-review` 后，后台会把这类新增信号交给会议搜索审核流程，判断会议是否已召开、录用或日程信息是否公开，并把后续复查计划写入 `state/scheduled_tasks.json`。

DBLP proceedings-like signals can trigger a conference-status review. With `--enable-signal-review`, newly discovered signals are sent through the conference search review flow. The reviewer decides whether the conference happened, whether accepted/program information is public, and writes follow-up checks to `state/scheduled_tasks.json`.

典型结果：

Typical outcomes:

```text
proceedings_indexed + accepted/program public
  -> 写入 conference_search_reviews.jsonl
  -> 生成 pending source candidate，等待人工 approve

proceedings_indexed + conference date visible but accepted info unclear/not public
  -> 不创建正式监听源
  -> scheduled_tasks.json 记录 next_check_after

weak/wrong-year/ambiguous search results
  -> 标记 needs_review
  -> 安排短周期复查或人工检查
```

手动处理某条历史事件：

Manually review one stored historical event:

```bash
python3 -m paper_watcher.main review-conference-signal \
  --event-id evt_xxx \
  --reviewer auto \
  --num-results 10
```

一次后台扫描做：

One background pass does:

```text
1. 读取全局 source 配置。
   Load global source config.
2. 读取用户库。
   Load user library.
3. 计算所有用户订阅 source_id 的并集。
   Determine the union of source IDs required by all users.
4. 读取 source_state。
   Load source_state.
5. 使用 ETag / Last-Modified 拉取来源。
   Fetch sources with ETag / Last-Modified.
6. 将 feed 或 venue 条目转换为规范化 paper item。
   Convert feed or venue entries into normalized paper items.
7. 按 paper_id 去重。
   Deduplicate by paper_id.
8. 追加新事件到 state/events.jsonl。
   Append new events to state/events.jsonl.
9. 更新 state/source_state.json。
   Update state/source_state.json.
```

重要行为：

Important behavior:

```text
后台不直接回答用户，只负责记录新增内容。
The background worker does not answer users directly; it only records newly discovered items.

坏的热更新配置会被拒绝，并写入 state/config_reload_errors.jsonl。
Bad hot-reload config is rejected and written to state/config_reload_errors.jsonl.
```

## 前台逻辑 / Foreground Logic

当前前台命令：

Current foreground command:

```text
paperwatcher foreground pull --user default
```

一次前台读取做：

One foreground pull does:

```text
1. 读取用户库。
   Load user library.
2. 读取 state/events.jsonl。
   Load state/events.jsonl.
3. 读取 state/user_cursors.json。
   Load state/user_cursors.json.
4. 选择匹配该用户订阅且新于 cursor 的事件。
   Select events matching this user and newer than the user's cursor.
5. 输出紧凑结果：标题 + 链接。
   Print a compact response: title + link.
6. 成功输出后更新该用户 cursor。
   Update this user's cursor after successful response.
```

当前回答格式：

Current answer format:

```text
New papers for default:

1. Paper title
   https://example.com/paper
```

后续 AstrBot 可以调用同一函数并发送到聊天。

Later, AstrBot can call the same function and send the response to chat.

## 用户管理 / User Management

当前提供基础订阅管理 CLI：

Basic subscription-management CLI is available:

```bash
python3 -m paper_watcher.main users list
python3 -m paper_watcher.main users subscribe --user root --source ndss_2026_accepted
python3 -m paper_watcher.main users unsubscribe --user root --source ndss_2026_accepted
```

默认 `--type auto` 会按 source 类型选择订阅槽位：

By default, `--type auto` chooses the subscription bucket from the source type:

```text
rss / arxiv       -> subscriptions.rss
dblp              -> subscriptions.indexed_venues
website_watch     -> subscriptions.website_watch
```

该命令只编辑 `config/users.yaml`，并在写入后重新加载配置做引用校验。

The command only edits `config/users.yaml` and reloads configuration after writing to validate references.

## 状态查看 / Status Dashboard

当前可以用一个命令查看系统概况：

Use one command to inspect the current system state:

```bash
python3 -m paper_watcher.main status
python3 -m paper_watcher.main status --format json
```

输出包含 source、用户、事件、候选源、会议审核、后台扫描和低频任务状态。

The output includes sources, users, events, candidates, conference reviews, background scans, and low-frequency scheduled task state.

## Web 监控页面 / Browser Monitor

项目提供一个只读 Web 监控页面，不需要额外前端构建步骤：

The project provides a read-only browser monitoring page with no frontend build step:

```bash
python3 -m paper_watcher.main web --host 127.0.0.1 --port 8080
```

远程浏览器访问时可以绑定到所有网卡，并设置访问 token：

For remote browser access, bind to all interfaces and set an access token:

```bash
python3 -m paper_watcher.main web \
  --host 0.0.0.0 \
  --port 8080 \
  --token "$PAPERWATCHER_WEB_TOKEN"
```

也可以从文件读取 token，避免 token 出现在进程列表中：

You can also read the token from a file, which avoids exposing it in the process list:

```bash
python3 -m paper_watcher.main web \
  --host 0.0.0.0 \
  --port 8080 \
  --token-file logs/monitor_web.token
```

浏览器访问：

Open in a browser:

```text
http://<server-ip>:8080/?token=<token>
```

页面展示：

The page shows:

```text
总体状态 / overall status
最近事件 / recent events
来源清单 / source list
来源健康状态 / source health
用户订阅覆盖 / user subscription coverage
会议审核记录 / conference reviews
候选监听源 / source candidates
```

候选监听源页面支持批准操作：

The source-candidate page supports approval actions:

```text
Preview
  预览将要写入 config/sources.yaml 的 source 配置。
  Preview the source config that would be written to config/sources.yaml.

Approve
  将 pending candidate 写入 config/sources.yaml，并加入 root 用户 website_watch 订阅。
  Write the pending candidate into config/sources.yaml and add it to root's website_watch subscriptions.
```

对应 API：

Related API:

```http
GET /api/candidates?status=pending&limit=20
X-PaperWatcher-Token: <token>
```

```http
POST /api/candidates/approve
Content-Type: application/json
X-PaperWatcher-Token: <token>

{"candidate_id": "cand_xxx", "dry_run": false, "actor": "astrbot:user123"}
```

```http
POST /api/candidates/reject
Content-Type: application/json
X-PaperWatcher-Token: <token>

{"candidate_id": "cand_xxx", "reason": "wrong year", "actor": "astrbot:user123"}
```

写操作会追加审计记录到 `state/candidate_actions.jsonl`。

Write operations append audit records to `state/candidate_actions.jsonl`.

该页面不是完全只读：`Candidates -> Approve` 会修改 `config/sources.yaml` 和 `config/users.yaml`。如果绑定 `0.0.0.0`，必须设置 token，并优先只在受信任网络或 SSH 隧道中访问。AstrBot 对接建议采用定时拉取 `GET /api/candidates?status=pending`，再由人类在聊天中确认 approve/reject。

The page is not fully read-only anymore: `Candidates -> Approve` modifies `config/sources.yaml` and `config/users.yaml`. If binding to `0.0.0.0`, always set a token, and prefer trusted networks or an SSH tunnel. AstrBot should use periodic pull via `GET /api/candidates?status=pending`, then ask a human to approve or reject in chat.

## systemd 服务 / systemd Services

项目提供两个 systemd unit 源文件：

The project includes two systemd unit source files:

```text
deploy/systemd/paperwatcher-web.service
deploy/systemd/paperwatcher-background.service
```

安装并启用：

Install and enable them:

```bash
sudo install -m 0644 deploy/systemd/paperwatcher-web.service /etc/systemd/system/paperwatcher-web.service
sudo install -m 0644 deploy/systemd/paperwatcher-background.service /etc/systemd/system/paperwatcher-background.service
sudo systemctl daemon-reload
sudo systemctl enable --now paperwatcher-web.service paperwatcher-background.service
```

常用管理命令：

Common management commands:

```bash
sudo systemctl status paperwatcher-web.service paperwatcher-background.service
sudo systemctl restart paperwatcher-web.service paperwatcher-background.service
sudo journalctl -u paperwatcher-web.service -u paperwatcher-background.service -f
```

这两个服务以 `paperdev` 用户运行，工作目录为项目根目录。Web 服务从 `logs/monitor_web.token` 读取访问 token，后台服务每 300 秒循环扫描并开启配置热更新。

Both services run as the `paperdev` user with the project root as the working directory. The web service reads its access token from `logs/monitor_web.token`; the background service scans every 300 seconds and reloads config changes between passes.

## 当前进展 / Current Stage

已实现基础能力：

Already implemented:

- 项目骨架 / Project skeleton
- YAML 配置加载器 / YAML configuration loader
- SQLite schema 初始化 / SQLite schema initialization
- 基础 CLI 命令 / Basic CLI commands
- RSS fetcher
- RSS 扫描写入 SQLite / RSS scanning into SQLite
- 评分和 Markdown 报告 / Scoring and Markdown run reports
- 本地 paper 查询 / Basic local paper query
- 用户库 `config/users.yaml` / User library in `config/users.yaml`
- 文件型后台事件存储 `state/` / File-backed background event storage in `state/`
- `background --once` 单次监控 / `background --once` monitoring pass
- `foreground pull --user <id>` 用户更新读取 / user-specific update retrieval
- DBLP fetcher，用于第一批 CCF-A/B 期刊和会议 / DBLP fetcher for the first CCF-A/B journal and conference sources
- `verify-sources` 来源可用性检查 / source availability checks
- 网络限速、重试和 HTTP 缓存 / Network request throttling, retry, and HTTP cache settings
- `events` 全局事件查看，支持 record-only 和 notifiable 过滤 / global event inspection with record-only and notifiable filters
- `background --loop --watch-config` 长期后台和配置热更新错误日志 / long-running background loop with config reload error logging
- `website_watch` 页面变化监控 / `website_watch` page change monitoring
- 已配置 5 个会议网页监听源 / 5 configured conference webpage watch sources
- 基于 `schedule.interval_seconds` 的后台扫描间隔 / background scan intervals based on `schedule.interval_seconds`
- `source-health` 来源健康状态查看 / `source-health` source health inspection
- `website_watch` 事件包含 `content_hash` 和页面摘录 / `website_watch` events include `content_hash` and page excerpts
- `website_watch` 可按配置提取单篇论文标题 / `website_watch` can extract individual paper titles by configuration
- Exa + Pydantic AI / DeepSeek 会议搜索审核 / Exa + Pydantic AI / DeepSeek conference search review
- `review-conferences` 批量会议审核 / `review-conferences` batch conference review
- `conference-reviews promote` 将高置信度审核转为候选监听源 / promote high-confidence reviews into source candidates
- 后台低频会议审核调度 / low-frequency conference review scheduling in the background loop
- `users` 订阅管理 CLI / `users` subscription-management CLI
- `status` 系统状态面板 / `status` system dashboard

下一步：

Next implementation step:

- 将 promotion 生成的候选源批量审核、批准和回归验证流程进一步自动化，并继续补齐 IMC、RAID、CCS 等会议的稳定 accepted papers / program URL。
- Further automate review, approval, and regression validation for promoted candidates, and continue adding stable accepted papers / program URLs for IMC, RAID, CCS, and related venues.

## 已配置监听源 / Configured Monitoring Sources

当前配置总数：

Current configured source count:

```text
38 sources total
37 enabled
```

`root` 当前订阅了 37 个启用/可监听源，包括：

`root` currently subscribes to 37 enabled or monitorable sources, including:

```text
DBLP conferences:
  CCS, USENIX Security, NDSS, IEEE S&P, SIGCOMM, NSDI, INFOCOM,
  MobiCom, CoNEXT, MobiSys, IMC, ICNP, DSN, ACSAC, RAID, KDD,
  ICDM, SIGIR, CIKM, WSDM

DBLP journals:
  IEEE TDSC, IEEE TIFS, IEEE/ACM TON, IEEE TKDE, IEEE TMC,
  IEEE JSAC, ACM TOPS, ACM TKDD, ACM TOIS, ACM TWEB

Record-only preprint sources:
  arXiv cs.CR, arXiv cs.LG
```

第一批 `website_watch` 会议网页源：

First batch of `website_watch` conference webpage sources:

```text
usenix_security_2026_accepted  USENIX Security 2026 Cycle 1 Accepted Papers
nsdi_2026_technical_sessions   NSDI 2026 Technical Sessions
ndss_2026_accepted             NDSS 2026 Accepted Papers
ieee_sp_2026_accepted          IEEE S&P 2026 Accepted Papers
sigcomm_2026_accepted          SIGCOMM 2026 Accepted Papers
```

这些来源由 `root` 用户订阅，用于开发期维护全局监听并集。

These sources are subscribed by the `root` user, so the development-stage backend monitors them as part of the global source union.

## 后台调度 / Background Scheduling

来源可以在 `config/sources.yaml` 中设置扫描间隔：

Sources can define scan intervals in `config/sources.yaml`:

```yaml
schedule:
  interval_seconds: 86400
```

后台循环 `background --loop` 会尊重该间隔，并在 `state/source_state.json` 中记录：

`background --loop` respects this interval and records the following fields in `state/source_state.json`:

```text
last_scan_at
next_scan_after
```

显式指定 `--source` 的手动扫描不受调度间隔限制，便于验证和调试。

Manual scans with `--source` bypass schedule intervals for verification and debugging.

## 基础用法 / Basic Usage

```bash
python -m paper_watcher.main validate-config
python -m paper_watcher.main init-db
python -m paper_watcher.main sources
python -m paper_watcher.main scan --once --source arxiv_cs_cr
python -m paper_watcher.main papers --recommendation read
python -m paper_watcher.main search "prompt injection"
python -m paper_watcher.main background --once
python -m paper_watcher.main background --loop --watch-config --interval 300
python -m paper_watcher.main foreground pull --user default
python -m paper_watcher.main foreground pull --user debug_user --peek --format json --limit 1
python -m paper_watcher.main foreground cursor --user debug_user --reset
python -m paper_watcher.main debug-server --port 8765
python -m paper_watcher.main verify-sources --type dblp
python -m paper_watcher.main source-health --failed
python -m paper_watcher.main source-health --type website_watch --format json
python -m paper_watcher.main events --limit 10
python -m paper_watcher.main events --record-only --limit 10
python -m paper_watcher.main events --notifiable --format json --limit 10
python scripts/send_debug_update.py debug-event --source-id debug_fake_rss --title "Debug Paper" --link "https://example.com/debug"
python scripts/send_debug_update.py fake-rss --port 8766 --title "Fake RSS Paper"
python scripts/send_debug_update.py fake-webpage --port 8767 --title "Accepted Papers" --body "Paper A"
python scripts/send_debug_update.py fake-webpage --port 8767 --title "Accepted Papers" --paper "Paper A" --paper "Paper B"
python -m unittest discover -s tests
```

## 调试注入 / Debug Update Injection

业务逻辑调试时，可以启动本地 debug 端口：

For business-logic debugging, run a local backend debug port:

```bash
python3 -m paper_watcher.main debug-server --host 127.0.0.1 --port 8765
```

另一个 shell 中发送伪更新：

From another shell, send a fake update:

```bash
python3 scripts/send_debug_update.py debug-event \
  --source-id debug_fake_rss \
  --title "Debug Paper Update" \
  --link "https://example.com/debug-paper"
```

debug server 会向 `state/events.jsonl` 追加一个事件。前台可以像读取真实后台事件一样读取它。

The debug server appends one event to `state/events.jsonl`. The foreground can retrieve it like any real background event.

```bash
python3 -m paper_watcher.main foreground pull --user debug_user --source debug_fake_rss
```

debug server 默认绑定 `127.0.0.1`。除非有明确理由，不应暴露到公网。

The debug server binds to `127.0.0.1` by default. Keep it local unless there is a clear reason to expose it.

独立调试工具也可以提供伪 RSS feed：

The standalone debug tool can also serve a fake RSS feed:

```bash
python3 scripts/send_debug_update.py fake-rss \
  --port 8766 \
  --title "Fake RSS Paper" \
  --link "https://example.com/fake-rss-paper" \
  --guid fake-rss-001
```

它也可以提供伪网页，用于测试 `website_watch` 的 `css_selector=main`：

It can also serve a fake webpage for testing `website_watch` with `css_selector=main`:

```bash
python3 scripts/send_debug_update.py fake-webpage \
  --port 8767 \
  --title "Accepted Papers" \
  --body "Paper A"
```

也可以用重复的 `--paper` 参数生成可解析的论文列表：

Use repeated `--paper` arguments to render a parsable paper list:

```bash
python3 scripts/send_debug_update.py fake-webpage \
  --port 8767 \
  --title "Accepted Papers" \
  --paper "Paper A" \
  --paper "Paper B"
```

`debug_fake_rss` 默认禁用。显式测试时可以指定 `--include-disabled`：

The configured `debug_fake_rss` source is disabled by default. To scan it explicitly for a test, use `--include-disabled`:

```bash
python3 -m paper_watcher.main background --once --source debug_fake_rss --include-disabled
```

前台读取选项：

Foreground read options:

```bash
python3 -m paper_watcher.main foreground pull --user debug_user --peek
python3 -m paper_watcher.main foreground pull --user debug_user --limit 5
python3 -m paper_watcher.main foreground pull --user debug_user --format json
python3 -m paper_watcher.main foreground pull --user debug_user --source debug_fake_rss
python3 -m paper_watcher.main foreground pull --user debug_user --since 2026-07-15T00:00:00+00:00
python3 -m paper_watcher.main foreground cursor --user debug_user --reset
```

端到端功能测试计划见：

See the end-to-end feature test plan:

```text
docs/functional_test_plan.md
```

## 事件查看 / Event Inspection

后台将发现内容写入全局文件事件流：

The background writes discovered items into the global file event stream:

```text
state/events.jsonl
```

查看近期事件且不推进任何用户 cursor：

Inspect recent events without advancing any user's foreground cursor:

```bash
python3 -m paper_watcher.main events --limit 10
python3 -m paper_watcher.main events --source arxiv_cs_cr --limit 10
python3 -m paper_watcher.main events --record-only --limit 10
python3 -m paper_watcher.main events --notifiable --limit 10
python3 -m paper_watcher.main events --format json --limit 10
```

`--record-only` 用于检查低优先级 arXiv 记录。`--notifiable` 用于查看前台用户可通过 `foreground pull` 接收的事件。

`--record-only` is useful for checking low-priority arXiv records. `--notifiable` shows events from sources that foreground users can receive through `foreground pull`.

`website_watch` 事件会在 raw 字段中保留页面变化信息：

`website_watch` events keep page-change details in the raw field:

```text
content_hash
excerpt
css_selector
source_url
```

如果来源配置了 `metadata.paper_selector`，后台还会为新增标题写入单篇论文事件：

If a source configures `metadata.paper_selector`, the background also writes individual paper events for newly seen titles:

```yaml
metadata:
  paper_selector: "main li"
  paper_title_selector: "a"
  paper_link_selector: "a"
```

首次扫描会 baseline 已有标题；后续只推送新增标题。

The first scan baselines existing titles; later scans only emit newly seen titles.

文本模式的 `events` 命令会直接显示 `content_hash` 和短摘录，便于快速判断页面变化。

The text-mode `events` command shows `content_hash` and a short excerpt, making webpage changes easier to inspect quickly.

## 来源健康状态 / Source Health

`source-health` 只读取本地状态文件，不触发网络请求：

`source-health` only reads local state files. It does not perform network requests:

```bash
python3 -m paper_watcher.main source-health
python3 -m paper_watcher.main source-health --source usenix_security_2026_accepted
python3 -m paper_watcher.main source-health --type website_watch
python3 -m paper_watcher.main source-health --failed
python3 -m paper_watcher.main source-health --due
python3 -m paper_watcher.main source-health --format json
```

它汇总：

It summarizes:

```text
last_scan_at
next_scan_after
due
last_success_at
last_error
verification_status
verification_checked_at
```

## 来源验证 / Source Verification

验证来源可用性，但不写入 paper event：

Verify source availability without writing paper events:

```bash
python3 -m paper_watcher.main verify-sources
python3 -m paper_watcher.main verify-sources --source dblp_ccs
python3 -m paper_watcher.main verify-sources --type dblp
python3 -m paper_watcher.main verify-sources --include-disabled
```

验证结果存储在：

Verification results are stored in:

```text
state/source_verification.json
```

当前支持：

Supported now:

```text
rss
arxiv
dblp
```

不支持的 source type 会显示为 `unsupported_source_type`，不会导致整个命令失败。

Unsupported source types are reported as `unsupported_source_type` instead of failing the whole command.

可能的验证状态：

Possible verification statuses:

```text
ok
cached_ok
unsupported_source_type
missing_required_field
network_error
http_429
http_503
parse_error
failed
```

网络行为配置在 `config/settings.yaml`：

Network behavior is configured in `config/settings.yaml`:

```yaml
network:
  per_host_delay_seconds:
    dblp.org: 5
  retries:
    max_attempts: 3
    backoff_seconds: 10
  cache:
    enabled: true
    dir: state/http_cache
```

`verify-sources` 在实时请求失败但存在历史成功响应时，可以回退到 `state/http_cache` 并报告 `cached_ok`。正式后台扫描在网络错误后不会使用缓存响应，因此旧缓存不会制造新增事件。

`verify-sources` may fall back to `state/http_cache` and report `cached_ok` when the live request fails but a previous successful response is available. Regular background scans do not use cached responses after a network error, so stale cache content cannot create new paper events.

安装包后也可以使用：

After installing the package, these commands are also available:

```bash
paperwatcher validate-config
paperwatcher init-db
paperwatcher sources
```

## Python 包镜像 / Python Package Mirror

在阿里云 ECS 上，优先配置 pip 使用阿里云 PyPI 镜像：

On Aliyun ECS, configure pip to use the Aliyun PyPI mirror first:

```bash
python3 -m pip config --user set global.index-url https://mirrors.aliyun.com/pypi/simple/
python3 -m pip config --user set global.timeout 60
python3 -m pip config --user set global.retries 10
```

安装开发和抓取依赖：

Install development and fetch dependencies:

```bash
python3 -m pip install --user --break-system-packages --no-build-isolation -e '.[dev,fetch]'
```

如果镜像源无法解决网络问题，下一步使用本机已运行的 mihomo 代理。

If the mirror cannot solve a network issue, use the local mihomo proxy already running on this machine as the next fallback.

## 配置 / Configuration

默认配置目录：

Default configuration path:

```text
config/
```

运行时配置：

Runtime settings:

```text
config/settings.yaml
```

LLM API key、webhook token、GitHub token 等敏感值必须通过环境变量或 `.env` 提供，不应提交到 YAML 配置或仓库。

Sensitive values such as LLM API keys, webhook tokens, and GitHub tokens must be provided by environment variables or `.env`, not committed into YAML configuration or the repository.

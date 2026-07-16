# 下一阶段开发计划

生成日期：2026-07-16

当前系统已经具备：

```text
用户订阅 source_id
后台扫描所有用户订阅并集
全局事件流 state/events.jsonl
前台按用户订阅和 cursor 读取
RSS / arXiv / DBLP fetcher 基础能力
root/default/debug_user 三类用户
```

下一阶段目标：先让当前配置的 CCF A/B DBLP/RSS 源可靠、可验证、可观测，再扩展长期后台和更多 source_type。

---

## 阶段 1：verify-sources

状态：最小实现已完成。

目标：验证每个 source 是否可抓取，并记录失败原因。

命令：

```bash
python3 -m paper_watcher.main verify-sources
python3 -m paper_watcher.main verify-sources --source dblp_ccs
python3 -m paper_watcher.main verify-sources --type dblp
python3 -m paper_watcher.main verify-sources --include-disabled
```

输出字段：

```text
source_id
source_type
enabled
status
item_count
error
elapsed_ms
```

状态文件：

```text
state/source_verification.json
```

状态分类：

```text
ok
unsupported_source_type
missing_required_field
network_error
http_429
http_503
parse_error
failed
```

验收标准：

```text
RSS/arXiv 源可验证。
DBLP 源可验证。
website_watch 源可验证。
OpenReview 等未实现来源显示 unsupported_source_type。
验证结果写入 source_verification.json。
测试覆盖成功、失败、unsupported。
```

已实现：

```text
paper_watcher/verifier.py
state/source_verification.json
verify-sources CLI
错误分类 classify_error
单元测试 tests/test_verifier.py
```

---

## 阶段 2：DBLP 请求节流、重试和缓存

状态：最小实现已完成。

目标：降低 DBLP 429/503/connection reset 对后台运行的影响。

任务：

```text
增加 per-host delay。
增加重试退避。
增加 state/http_cache/ 文件缓存。
DBLP 扫描按源串行低频进行。
```

建议配置：

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

已实现：

```text
paper_watcher/http_client.py
paper_watcher/network.py
config/settings.yaml network 配置
RSSFetcher / DBLPFetcher 统一通过 RateLimitedHttpClient 请求
background / scanner 正式扫描不使用错误时缓存，避免旧缓存制造新增事件
verify-sources 允许缓存降级，并用 cached_ok 标记
单元测试 tests/test_http_client.py
```

验收标准：

```text
连续验证多个 DBLP 源时不会无间隔打 DBLP。
429/503 会分类记录。
缓存只用于诊断，不制造假新增事件。
```

---

## 阶段 3：事件查看与 record-only 可观测性

状态：最小实现已完成。

目标：能直接查看全局事件流，尤其是 arXiv record-only 事件。

命令：

```bash
python3 -m paper_watcher.main events --limit 10
python3 -m paper_watcher.main events --source arxiv_cs_cr --limit 10
python3 -m paper_watcher.main events --record-only --limit 10
python3 -m paper_watcher.main events --notifiable --limit 10
```

验收标准：

```text
arXiv 事件可查但不进入 foreground 默认推送。
CCF DBLP 事件可查且可由订阅用户读取。
```

已实现：

```text
paper_watcher/events.py
events CLI
--source / --limit / --format json
--record-only / --notifiable
单元测试 tests/test_events.py
```

---

## 阶段 4：后台长期运行和配置热更新

状态：最小实现已完成。

目标：从 `background --once` 变成可长期运行的后台。

命令：

```bash
python3 -m paper_watcher.main background --loop --watch-config
```

任务：

```text
配置 fingerprint。
配置变化时 reload。
坏配置保留旧配置。
新增 source 首次 baseline。
reload 错误写入 state/config_reload_errors.jsonl。
```

验收标准：

```text
配置变更后无需重启后台即可生效。
坏配置不会中断后台。
```

已实现：

```text
paper_watcher/config_watcher.py
ConfigSnapshot
配置 fingerprint：path + mtime_ns + size
background --loop
background --watch-config
background --interval
坏配置保留旧 ConfigSnapshot
reload 错误写入 state/config_reload_errors.jsonl
单元测试 tests/test_background_loop.py
```

---

## 阶段 5：WebsiteWatcher 最小实现

状态：最小实现已完成。

目标：先支持会议 accepted papers 页面变化监控，不急于解析论文列表。

任务：

```text
抓取 watch_url。
按 css_selector 提取正文。
计算 content_hash。
首次 baseline。
hash 变化写入 Website changed 事件。
```

第一批：

```text
USENIX Security
NDSS
IEEE S&P
SIGCOMM
IMC
RAID
```

已实现：

```text
docs/website_watcher_implementation_plan.md
paper_watcher/fetchers/website_watcher.py
background 接入 website_watch
verify-sources 接入 website_watch
scripts/send_debug_update.py fake-webpage
单元测试 tests/test_website_watcher.py
本地 fake-webpage 端到端验证 baseline 和 hash 变化事件
```

---

## 阶段 6：OpenReviewFetcher

目标：监听 ICML / NeurIPS / ICLR 等 AI 安全相关来源。

任务：

```text
openreview_venue_id 配置。
accepted decision 过滤。
提取 title/authors/abstract/pdf/keywords。
年度 venue id 不硬编码。
```

---

## 当前执行顺序

当前立即执行：

```text
补齐更多会议网页 URL，改进 authors/PDF 解析与会议专用 selector
```

已完成：

```text
阶段 1：verify-sources
阶段 2：DBLP 请求节流、重试和缓存
阶段 3：事件查看与 record-only 可观测性
阶段 4：后台长期运行和配置热更新
阶段 5：WebsiteWatcher 最小实现
扩展会议页面监听清单与后台调度细化
source-health 来源健康状态查看
website_watch 事件 raw 中保留 content_hash / excerpt / css_selector
website_watch 配置化解析 accepted papers 单篇标题
```

扩展会议页面监听清单与后台调度细化已完成的最小内容：

```text
新增 usenix_security_2026_accepted 官方 cycle 1 页面。
新增 nsdi_2026_technical_sessions。
新增 ndss_2026_accepted。
新增 ieee_sp_2026_accepted。
新增 sigcomm_2026_accepted。
root 用户订阅上述 website_watch 来源。
arXiv / DBLP / website_watch 增加 schedule.interval_seconds。
background --loop 根据 next_scan_after 跳过未到期来源。
手动 --source 扫描绕过调度，便于测试。
```

source-health 与 website_watch 事件摘要已完成的最小内容：

```text
新增 paper_watcher/source_health.py。
新增 source-health CLI。
支持 --source / --type / --failed / --due / --format json。
source-health 只读取本地 state，不触发网络请求。
events JSON 输出包含 raw。
events 文本输出对 website_watch 显示 content_hash 和 excerpt。
background 事件 raw 合并 Paper.raw，保留网页 hash 和摘录。
单元测试 tests/test_source_health.py。
```

website_watch 单篇标题解析已完成的最小内容：

```text
支持 metadata.paper_selector。
支持 metadata.paper_title_selector。
支持 metadata.paper_link_selector。
未配置 paper_selector 时保持页面级事件模式。
首次扫描 baseline 已有标题，不推送旧论文。
后续扫描只为新增 title 生成 website-paper 事件。
fake-webpage 支持重复 --paper 参数。
单元测试覆盖标题提取、相对链接补全、baseline 与新增标题事件。
```

# 全局监听并集与前台订阅过滤设计

生成日期：2026-07-16

本文档记录当前 PaperWatcher 的核心运行逻辑。

---

## 1. 总体原则

后台不再按用户分别记录监听结果。

后台只做一件事：

```text
扫描所有用户订阅 source_id 的并集，并把发现结果写入统一事件流。
```

前台负责：

```text
根据用户自己的订阅 source_id 集合，以及该用户 cursor，筛选统一事件流并生成回复。
```

也就是说：

```text
用户区只保存读取位置，不保存一份独立消息队列。
```

当前文件存储：

```text
state/events.jsonl       # 全局事件流
state/source_state.json  # source 级扫描状态和 baseline
state/user_cursors.json  # user 级读取位置
```

---

## 2. root 用户

开发期间创建逻辑用户：

```text
root
```

root 的作用：

```text
订阅系统当前要监控的全部 source。
确保后台扫描并集包含这些 source。
不代表真实人类用户必须接收所有推送。
```

普通用户只需要在 `config/users.yaml` 中订阅自己想看的 source。

---

## 3. 事件写入规则

后台扫描一个 source 后，如果发现新增论文，写入：

```text
state/events.jsonl
```

事件包含：

```json
{
  "event_id": "evt_...",
  "seen_at": "...",
  "source_id": "dblp_ccs",
  "source_type": "dblp",
  "paper_id": "paper_...",
  "title": "...",
  "link": "...",
  "matched_users": [],
  "raw": {}
}
```

`matched_users` 字段目前保留为兼容字段，但业务逻辑不再依赖它。

---

## 4. 前台读取规则

前台收到：

```bash
paperwatcher foreground pull --user default
```

实际执行：

```text
1. 读取 config/users.yaml。
2. 找到 default 用户订阅的 source_id 集合。
3. 排除 notification_policy=record_only 的 source。
4. 读取 state/user_cursors.json 中 default 的 cursor。
5. 遍历 state/events.jsonl。
6. 只返回：
   - source_id 属于该用户订阅集合
   - source 的 notification_policy=notify
   - event.seen_at 晚于用户 cursor
7. 返回后将 cursor 推进到本次最后一条已返回事件。
```

这使得同一个全局事件可以被多个用户读取，而无需后台复制事件。

---

## 5. record_only 来源

`notification_policy: record_only` 表示：

```text
后台记录，前台不推送。
```

典型来源：

```text
arXiv
高噪声补充源
仅用于趋势观察的源
```

arXiv 当前策略：

```yaml
source_type: arxiv
priority: 1
notification_policy: record_only
```

TODO：arXiv 后续按发布者所属科研团队进行记录。

---

## 6. 当前最容易实现的一批监听源

依据 `paper_sources_monitoring_catalog.md`，当前先选择 DBLP 作为正式 CCF A/B 来源的第一批监听方式。

原因：

```text
DBLP 结构化程度高。
不依赖会议每年变化的 accepted papers URL。
适合做正式发表兜底源。
实现成本低于 OpenReview、出版社 Alert、网页解析。
```

第一批 root 订阅：

```text
DBLP CCS                  CCF-A 安全
DBLP USENIX Security      CCF-A 安全
DBLP NDSS                 CCF-A 安全
DBLP IEEE S&P             CCF-A 安全
DBLP SIGCOMM              CCF-A 网络
DBLP IMC                  CCF-B 网络
DBLP RAID                 CCF-B 安全
DBLP KDD                  CCF-A 数据挖掘
DBLP IEEE TDSC            CCF-A 安全期刊
DBLP IEEE TIFS            CCF-A 安全期刊
DBLP IEEE/ACM TON         CCF-A 网络期刊
DBLP IEEE TKDE            CCF-A 数据挖掘期刊
```

同时保留：

```text
arXiv cs.CR
arXiv cs.LG
```

但 arXiv 只记录不推送。

---

## 7. 后续扩展顺序

推荐顺序：

1. 完善 DBLP venue key 验证和错误重试。
2. 增加更多 CCF-A/B 期刊 DBLP 源。
3. 实现 OpenReviewFetcher。
4. 实现 WebsiteWatcher。
5. 实现出版社 RSS / TOC feed 验证工具。
6. 实现监听清单热更新。


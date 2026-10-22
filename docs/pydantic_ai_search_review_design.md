# Pydantic AI 搜索结果审核设计 / Pydantic AI Search Review Design

生成日期：2026-07-17

本文档记录如何用 Pydantic AI 对模糊搜索结果进行低频审核。

This document records how PaperWatcher uses Pydantic AI to review fuzzy search results at low frequency.

---

## 1. 目标 / Goal

智能体只回答三个问题：

The agent only answers three questions:

```text
这个会议这一年是否召开？
Is this conference happening in the target year?

如果可见，什么时候召开或有哪些关键日期？
If visible, when is it held or what key dates are available?

录用信息、program、accepted papers 或 proceedings 是否已经公开？
Is accepted-paper, program, accepted-papers, or proceedings information public?
```

智能体不负责：

The agent is not responsible for:

```text
直接搜索互联网。
Searching the internet directly.

直接修改 config/sources.yaml。
Editing config/sources.yaml directly.

直接批准正式监听源。
Approving formal monitoring sources directly.
```

---

## 2. 当前边界 / Current Boundary

当前实现支持两种输入方式：

The current implementation supports two input paths:

```text
1. 读取已有搜索结果 JSON 文件。
   Read an existing search-result JSON file.

2. 使用 Exa 搜索会议页面信号，然后立即审核。
   Search conference-page signals with Exa, then review them immediately.
```

搜索结果 JSON 文件格式：

Search-result JSON file format:

```json
{
  "venue_id": "ndss",
  "year": 2027,
  "query": "NDSS 2027 accepted papers",
  "results": [
    {
      "title": "NDSS Symposium 2027 Accepted Papers",
      "url": "https://www.ndss-symposium.org/ndss2027/accepted-papers/",
      "snippet": "Accepted papers for NDSS 2027 are now available."
    }
  ]
}
```

Exa 搜索会被归一化为同样的结构，因此 reviewer 不感知搜索 API 细节。

Exa search is normalized into the same structure, so the reviewer does not depend on search API details.

---

## 3. Reviewer / Reviewer

当前支持两种 reviewer：

Two reviewers are supported:

```text
rule_based
pydantic_ai
```

`rule_based` 是 fallback，不依赖外部模型。

`rule_based` is the fallback and does not depend on external models.

`pydantic_ai` 是可选 reviewer，需要安装可选依赖并配置 API key。

`pydantic_ai` is optional and requires the optional dependency plus an API key.

安装：

Install:

```bash
pip install -e '.[fetch,agent]'
```

配置：

Config:

```text
config/agent_review.yaml
.env
```

`.env` 示例：

`.env` example:

```text
DEEPSEEK_API_KEY=...
DEEPSEEK_API_URL=https://api.deepseek.com
DEEPSEEK_API_MODEL=deepseek-v4-pro
EXA_API_KEY=...
EXA_API_URL=https://api.exa.ai/search
```

实现上使用 Pydantic AI 的 OpenAI-compatible provider 调 DeepSeek；为兼容 DeepSeek thinking mode，当前不使用 provider-side tool/structured output，而是要求模型返回纯 JSON，再在本地用 Pydantic 校验。

The implementation calls DeepSeek through Pydantic AI's OpenAI-compatible provider. To stay compatible with DeepSeek thinking mode, it does not use provider-side tool/structured output; instead, the model returns plain JSON and local Pydantic validation checks the schema.

---

## 4. 命令 / Commands

规则审核：

Rule-based review:

```bash
python3 -m paper_watcher.main review-search-results \
  --input /path/to/results.json \
  --reviewer rule_based
```

Pydantic AI 审核：

Pydantic AI review:

```bash
python3 -m paper_watcher.main review-search-results \
  --input /path/to/results.json \
  --reviewer pydantic_ai
```

仅预览、不写状态：

Preview without writing state:

```bash
python3 -m paper_watcher.main review-search-results \
  --input /path/to/results.json \
  --dry-run
```

查看审核记录：

List review records:

```bash
python3 -m paper_watcher.main conference-reviews
python3 -m paper_watcher.main conference-reviews --venue ndss --year 2027
```

批量审核会议 profile：

Batch review venue profiles:

```bash
python3 -m paper_watcher.main review-conferences \
  --year 2027 \
  --reviewer auto \
  --num-results 2
```

批处理按 `config/venue_profiles.yaml` 逐个执行搜索和审核。单个会议失败不会中断整批任务；失败会进入 batch summary。加 `--dry-run` 时不写入 `state/conference_search_reviews.jsonl`。

The batch command searches and reviews each profile in `config/venue_profiles.yaml`. A single venue failure does not stop the whole batch; failures are reported in the batch summary. With `--dry-run`, it does not write `state/conference_search_reviews.jsonl`.

使用 Exa 直接搜索：

Search directly with Exa:

```bash
python3 -m paper_watcher.main search-conference \
  --venue ndss \
  --year 2027 \
  --num-results 2
```

搜索并立即审核，但不写入状态：

Search and review immediately, without writing state:

```bash
python3 -m paper_watcher.main search-review-conference \
  --venue ndss \
  --year 2027 \
  --reviewer pydantic_ai \
  --dry-run \
  --num-results 2
```

保存搜索结果，供后续离线审核：

Save search results for later offline review:

```bash
python3 -m paper_watcher.main search-conference \
  --venue ndss \
  --year 2027 \
  --save state/debug_ndss_2027_search.json
```

将高置信度审核结果提升为候选监听源：

Promote a high-confidence review into a source candidate:

```bash
python3 -m paper_watcher.main conference-reviews promote \
  --venue ndss \
  --year 2026 \
  --dry-run

python3 -m paper_watcher.main conference-reviews promote \
  --id review_xxx
```

promotion 条件：

Promotion requirements:

```text
action = monitor_accepted_page
accepted_info_status = public
confidence >= agent_review.policy.monitor_min_confidence
accepted_info_url is present
```

promotion 只生成 `state/source_candidates.jsonl` 候选源。正式加入监听清单仍需要：

Promotion only generates a candidate in `state/source_candidates.jsonl`. Formal monitoring still requires:

```bash
python3 -m paper_watcher.main candidates approve --id cand_xxx
```

---

## 5. 输出结构 / Output Schema

审核结果写入：

Review results are written to:

```text
state/conference_search_reviews.jsonl
```

核心字段：

Core fields:

```text
conference_status:
  scheduled
  likely_scheduled
  not_found
  unclear

accepted_info_status:
  public
  not_public
  unclear

action:
  monitor_accepted_page
  monitor_cfp_page
  needs_review
  ignore
```

`monitor_accepted_page` 只表示“应该进入候选来源流程”，不等于自动写入正式监听清单。

`monitor_accepted_page` only means "should enter the candidate-source flow"; it does not automatically edit the formal monitoring list.

---

## 6. Exa 搜索接入 / Exa Search Integration

当前搜索接入位于：

The current search integration lives in:

```text
paper_watcher/conference_search.py
```

职责：

Responsibilities:

```text
从 config/venue_profiles.yaml 读取会议别名、官方域名和 URL pattern。
Read aliases, official domains, and URL patterns from config/venue_profiles.yaml.

根据 venue_id + year 生成低频搜索 query。
Generate low-frequency search queries from venue_id + year.

用 Exa 拉取搜索结果。
Fetch search results with Exa.

归一化为 SearchReviewInput。
Normalize results into SearchReviewInput.
```

审核器仍然只看结构化搜索结果。

The reviewer still only consumes structured search results.

后续如果需要替换或补充搜索 API，可以把 `conference_search.py` 中的 client 抽成 provider 接口。当前阶段先保持单文件实现，降低移植和部署复杂度。

If another search API is needed later, the client inside `conference_search.py` can be extracted into a provider interface. For now, the single-file implementation keeps portability and deployment simple.

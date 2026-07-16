from __future__ import annotations

from dataclasses import replace

from paper_watcher.models import AppConfig, Paper, Recommendation, Source


def score_paper(paper: Paper, source: Source, config: AppConfig) -> Paper:
    score = 0.0
    ccf_scores = config.scoring.base_scores.get("ccf", {})
    venue_type_scores = config.scoring.base_scores.get("venue_type", {})
    score += float(ccf_scores.get(paper.ccf_level.value, 0))
    score += float(venue_type_scores.get(paper.venue_type.value, 0))
    score += source.priority * config.scoring.priority_weight

    text = " ".join(part for part in [paper.title, paper.abstract or ""] if part).lower()
    tags = list(dict.fromkeys(paper.tags + _matching_tags(text, config)))

    for keyword, value in config.keywords.strong_keywords.items():
        if keyword.lower() in text:
            score += value
    for keyword, value in config.keywords.medium_keywords.items():
        if keyword.lower() in text:
            score += value
    for keyword, value in config.keywords.negative_keywords.items():
        if keyword.lower() in text:
            score += value

    recommendation = recommendation_for_score(score, config)
    return replace(paper, score=round(score, 2), recommendation=recommendation, tags=tags)


def recommendation_for_score(score: float, config: AppConfig) -> Recommendation:
    thresholds = config.scoring.recommendation_thresholds
    if score >= thresholds[Recommendation.READ]:
        return Recommendation.READ
    if score >= thresholds[Recommendation.SKIM]:
        return Recommendation.SKIM
    if score >= thresholds[Recommendation.ARCHIVE]:
        return Recommendation.ARCHIVE
    return Recommendation.IGNORE


def _matching_tags(text: str, config: AppConfig) -> list[str]:
    tags: list[str] = []
    for group, keywords in (
        ("strong", config.keywords.strong_keywords),
        ("medium", config.keywords.medium_keywords),
        ("negative", config.keywords.negative_keywords),
    ):
        for keyword in keywords:
            if keyword.lower() in text:
                tags.append(f"{group}:{keyword}")
    return tags

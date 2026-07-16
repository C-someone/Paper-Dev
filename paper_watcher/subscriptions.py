from __future__ import annotations

from paper_watcher.models import AppConfig, NotificationPolicy, User


def user_subscription_source_ids(user: User) -> set[str]:
    source_ids = {subscription.source_id for subscription in user.subscriptions.rss}
    for subscription in user.subscriptions.indexed_venues:
        source_id = subscription.get("source_id") if isinstance(subscription, dict) else None
        if isinstance(source_id, str) and source_id:
            source_ids.add(source_id)
    for subscription in user.subscriptions.website_watch:
        source_id = subscription.get("source_id") if isinstance(subscription, dict) else None
        if isinstance(source_id, str) and source_id:
            source_ids.add(source_id)
    return source_ids


def all_subscribed_source_ids(config: AppConfig) -> set[str]:
    source_ids: set[str] = set()
    for user in config.users.users:
        source_ids.update(user_subscription_source_ids(user))
    return source_ids


def notifiable_source_ids_for_user(config: AppConfig, user: User) -> set[str]:
    source_by_id = {source.id: source for source in config.sources.sources}
    result: set[str] = set()
    for source_id in user_subscription_source_ids(user):
        source = source_by_id.get(source_id)
        if source and source.notification_policy == NotificationPolicy.NOTIFY:
            result.add(source_id)
    return result

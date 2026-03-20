from __future__ import annotations

import asyncio
import time

from Scweet.api_engine import ApiEngine
from Scweet.manifest import ManifestModel
from Scweet.models import FollowsRequest


class _ManifestProvider:
    def __init__(self, manifest: ManifestModel):
        self.manifest = manifest

    async def get_manifest(self) -> ManifestModel:
        return self.manifest


class _AccountsRepo:
    def __init__(self):
        self.usage_calls: list[dict] = []
        self.release_calls: list[dict] = []
        self.heartbeat_calls: list[dict] = []

    async def record_usage(self, lease_id: str, pages: int = 0, tweets: int = 0):
        self.usage_calls.append(
            {
                "lease_id": lease_id,
                "pages": int(pages),
                "tweets": int(tweets),
            }
        )
        return None

    async def release(self, lease_id: str, fields_to_set: dict | None = None, fields_to_inc: dict | None = None):
        self.release_calls.append(
            {
                "lease_id": lease_id,
                "fields_to_set": dict(fields_to_set or {}),
                "fields_to_inc": dict(fields_to_inc or {}),
            }
        )
        return True

    async def heartbeat(self, lease_id: str, extend_by_s: int):
        self.heartbeat_calls.append({"lease_id": lease_id, "extend_by_s": int(extend_by_s)})
        return True


def _manifest() -> ManifestModel:
    return ManifestModel.model_validate(
        {
            "version": "test",
            "query_ids": {
                "search_timeline": "qid_search",
                "user_lookup_screen_name": "qid_user",
                "following": "qid_following",
            },
            "endpoints": {
                "search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline",
                "user_lookup_screen_name": "https://x.com/i/api/graphql/{query_id}/UserByScreenName",
                "following": "https://x.com/i/api/graphql/{query_id}/Following",
            },
            "features": {},
            "timeout_s": 5,
        }
    )


def test_follows_records_unique_items_in_usage_counter():
    async def _run():
        repo = _AccountsRepo()
        engine = ApiEngine(
            config={
                "requests_per_min": 10_000,
                "min_delay_s": 0.0,
                "lease_heartbeat_s": 0.0,
            },
            accounts_repo=repo,
            manifest_provider=_ManifestProvider(_manifest()),
            session_factory=lambda: object(),
        )

        async def _acquire_follows_session():
            return object(), {"id": "1", "username": "acct-a"}, "lease-a", None

        async def _resolve_target_username(target):
            return target.get("username")

        async def _graphql_get(url, params, timeout_s, session=None, account_context=None):
            _ = params, timeout_s, session, account_context
            if "UserByScreenName" in url:
                return {"data": {}}, 200, {"x-rate-limit-remaining": "10"}, ""
            return {"data": {}}, 200, {"x-rate-limit-remaining": "9"}, ""

        engine._acquire_follows_session = _acquire_follows_session  # type: ignore[method-assign]
        engine._resolve_target_username = _resolve_target_username  # type: ignore[method-assign]
        engine._graphql_get = _graphql_get  # type: ignore[method-assign]
        engine._build_user_lookup_params = lambda username, manifest: {"u": username}  # type: ignore[method-assign]
        engine._build_follows_params = (
            lambda user_id, cursor, manifest, operation, runtime_hints=None: {"id": user_id, "cursor": cursor}
        )  # type: ignore[method-assign]
        engine._extract_user_result = lambda payload: {"rest_id": "uid-1"}  # type: ignore[method-assign]
        engine._extract_follows_users_and_cursor = (
            lambda payload: (
                [
                    {"rest_id": "u1", "legacy": {"screen_name": "alice"}},
                    {"rest_id": "u1", "legacy": {"screen_name": "alice"}},
                ],
                None,
            )
        )  # type: ignore[method-assign]

        out = await engine.get_follows(
            FollowsRequest(
                targets=[{"username": "OpenAI"}],
                follow_type="following",
                max_pages_per_profile=1,
            )
        )

        assert out["status_code"] == 200
        assert len(out["follows"]) == 1
        assert len(repo.usage_calls) == 2
        assert repo.usage_calls[0]["tweets"] == 0
        assert repo.usage_calls[1]["tweets"] == 1

    asyncio.run(_run())


def test_follows_preemptive_rate_limit_remaining_handoffs_and_cools_down_account():
    async def _run():
        reset_ts = int(time.time() + 70)
        repo = _AccountsRepo()
        engine = ApiEngine(
            config={
                "requests_per_min": 10_000,
                "min_delay_s": 0.0,
                "lease_heartbeat_s": 0.0,
                "max_account_switches": 1,
                "cooldown_jitter_s": 0,
            },
            accounts_repo=repo,
            manifest_provider=_ManifestProvider(_manifest()),
            session_factory=lambda: object(),
        )

        sessions = [
            (object(), {"id": "1", "username": "acct-a"}, "lease-a", None),
            (object(), {"id": "2", "username": "acct-b"}, "lease-b", None),
        ]
        timeline_calls = 0

        async def _acquire_follows_session():
            if not sessions:
                return None, None, None, None
            return sessions.pop(0)

        async def _resolve_target_username(target):
            return target.get("username")

        async def _graphql_get(url, params, timeout_s, session=None, account_context=None):
            _ = params, timeout_s, session, account_context
            nonlocal timeline_calls
            if "UserByScreenName" in url:
                return {"data": {}}, 200, {"x-rate-limit-remaining": "8"}, ""
            timeline_calls += 1
            if timeline_calls == 1:
                return {
                    "data": {"page": 1},
                }, 200, {
                    "x-rate-limit-remaining": "0",
                    "x-rate-limit-reset": str(reset_ts),
                }, ""
            return {"data": {"page": 2}}, 200, {"x-rate-limit-remaining": "7"}, ""

        def _extract_follows_users_and_cursor(payload):
            page = ((payload or {}).get("data") or {}).get("page")
            if page == 1:
                return [{"rest_id": "u1", "legacy": {"screen_name": "alice"}}], "CURSOR-2"
            return [{"rest_id": "u2", "legacy": {"screen_name": "bob"}}], None

        engine._acquire_follows_session = _acquire_follows_session  # type: ignore[method-assign]
        engine._resolve_target_username = _resolve_target_username  # type: ignore[method-assign]
        engine._graphql_get = _graphql_get  # type: ignore[method-assign]
        engine._build_user_lookup_params = lambda username, manifest: {"u": username}  # type: ignore[method-assign]
        engine._build_follows_params = (
            lambda user_id, cursor, manifest, operation, runtime_hints=None: {"id": user_id, "cursor": cursor}
        )  # type: ignore[method-assign]
        engine._extract_user_result = lambda payload: {"rest_id": "uid-1"}  # type: ignore[method-assign]
        engine._extract_follows_users_and_cursor = _extract_follows_users_and_cursor  # type: ignore[method-assign]

        out = await engine.get_follows(
            FollowsRequest(
                targets=[{"username": "OpenAI"}],
                follow_type="following",
                max_pages_per_profile=5,
                cursor_handoff=True,
                max_account_switches=1,
            )
        )

        assert out["status_code"] == 200
        assert len(out["follows"]) == 2
        assert out["meta"]["retries"] == 1

        rate_limited = [
            row for row in repo.release_calls if row["lease_id"] == "lease-a" and row["fields_to_set"].get("cooldown_reason") == "rate_limit"
        ]
        assert len(rate_limited) == 1
        assert rate_limited[0]["fields_to_set"]["available_til"] == float(reset_ts)

    asyncio.run(_run())

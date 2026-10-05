"""Run inside the app container; assertions fail the server acceptance run."""
import asyncio
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import httpx

from backend import news

BASE = "http://127.0.0.1:8000"
EVIDENCE = news.DB_PATH.parent / "acceptance"


def api(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return json.load(response)


def identities():
    with news.connect() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT id,source_id,canonical_url,first_seen_at FROM articles ORDER BY id")]


def check_api():
    counts = {}
    for source in (None, "nasa", "esa"):
        ids, cursor, cursors = [], None, set()
        for _ in range(10000):
            params = {"limit": 2}
            if source:
                params["source"] = source
            if cursor:
                params["cursor"] = cursor
            page = api("/api/news?" + urllib.parse.urlencode(params))
            assert len(page["items"]) <= 2
            for item in page["items"]:
                assert source is None or item["source_id"] == source
                assert news.allowed_url(item["original_url"], news.SOURCES[item["source_id"]]["domain"])
                assert item["id"] not in ids, "Pagination repeated an article"
                ids.append(item["id"])
            cursor = page["next_cursor"]
            if not cursor:
                break
            assert cursor not in cursors, "Pagination did not advance"
            cursors.add(cursor)
        else:
            raise AssertionError("Pagination did not terminate")
        with news.connect() as conn:
            expected = [row[0] for row in conn.execute(
                "SELECT id FROM articles" + (" WHERE source_id=?" if source else "") +
                " ORDER BY COALESCE(published_at,'') DESC,id DESC", (source,) if source else ())]
        assert ids == expected, "Pagination lost records or changed ordering"
        assert ids, "Source has no real articles"
        assert api(f"/api/news/{ids[0]}")["id"] == ids[0]
        counts[source or "all"] = len(ids)
    for path, status in (("/api/news?source=unknown", 400), ("/api/news?limit=51", 422),
                         ("/api/news?cursor=broken", 400)):
        try:
            api(path)
        except urllib.error.HTTPError as error:
            assert error.code == status
        else:
            raise AssertionError(f"Expected HTTP {status}: {path}")
    with urllib.request.urlopen(BASE, timeout=10) as response:
        assert response.status == 200
        assert b"news-ui.js" in response.read()
    return counts


async def collection_checks():
    rounds = []
    for _ in range(2):
        result = await news.collect_all()
        assert all("error" not in item for item in result), result
        rounds.append(result)
    # Capture fresh real upstream payloads, then replay those exact bytes through
    # the collector twice. This tests UPSERT even when upstream supports 304.
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        for source in news.SOURCES:
            if news.SOURCES[source]['collector_kind'] != 'rss':
                continue
            raw, _ = await news.fetch_feed(client, source, {})
            assert raw is not None
            records, rejected = news.parse_feed(source, raw)
            assert records, f"Empty upstream feed: {source}"
            transport = httpx.MockTransport(lambda request: httpx.Response(200, content=raw))
            async with httpx.AsyncClient(transport=transport) as replay:
                first = await news.collect_source(replay, source)
                assert "error" not in first, first
                before = identities()
                second = await news.collect_source(replay, source)
                assert "error" not in second, second
                assert identities() == before, "Same feed created or replaced article identities"
            rounds.append({"source": source, "real_payload_records": len(records),
                           "rejected": rejected, "exact_payload_replay": "passed"})
    with news.connect() as conn:
        duplicates = conn.execute("SELECT source_id,canonical_url,COUNT(*) FROM articles "
                                  "GROUP BY source_id,canonical_url HAVING COUNT(*)>1").fetchall()
    assert not duplicates
    return rounds


async def failure_check():
    before = identities()
    states = {row['id']: news.source_state(row['id']) for row in news.sources_status() if row['enabled']}
    try:
        def response(request):
            raise httpx.ConnectError("Acceptance: simulated upstream connection failure", request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            results = await asyncio.gather(*(news.collect_source(client, source) for source in states))
        assert all("error" in result for result in results)
        assert identities() == before, "Source failure removed history"
        for row in api("/api/news/sources")["items"]:
            if row['id'] not in states:
                continue
            assert row["last_error"] is True
            assert row["last_success_at"] == states[row["id"]]["last_success_at"]
        counts = check_api()
        return {"injection": "mock HTTP transport connection failure; real collector and persistent database",
                "history_readable": counts, "success_timestamp_preserved": True}
    finally:
        # Restore only metadata changed by the isolated failure test.
        with news.connect() as conn:
            for source, state in states.items():
                conn.execute("UPDATE sources SET last_attempt_at=?,last_success_at=?,last_error=?,last_result=?,retry_after_at=? WHERE id=?",
                             (state["last_attempt_at"], state["last_success_at"], state["last_error"], state['last_result'], state['retry_after_at'], source))


def main():
    EVIDENCE.mkdir(exist_ok=True)
    phase = sys.argv[1]
    if phase == "before":
        # Allow startup's scheduled round to finish before probing the same DB.
        for _ in range(60):
            rows = api("/api/news/sources")["items"]
            if all(row["last_success_at"] or row["last_error"] for row in rows if row['enabled']):
                break
            time.sleep(1)
        report = {"started_at": news.now(), "real_collection": asyncio.run(collection_checks()),
                  "filter_and_pagination": check_api(),
                  "source_failure": asyncio.run(failure_check()), "baseline": identities(),
                  "browser_interaction": "pending manual/browser verification"}
        (EVIDENCE / "before.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    elif phase == "after":
        report = json.loads((EVIDENCE / "before.json").read_text())
        current = {row["id"]: row for row in identities()}
        assert all(current.get(row["id"]) == row for row in report["baseline"]), "Rebuild lost historical identities"
        report.update(completed_at=news.now(), container_recreation="passed",
                      after_recreation_api=check_api())
        (EVIDENCE / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        raise ValueError("Use before or after")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

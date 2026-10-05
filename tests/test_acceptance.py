"""Validate acceptance assertions locally without claiming server acceptance."""
import asyncio
import json
import os
import tempfile
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import news
from backend.app import app
from test_news import rss
from tools import accept_news


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db, self.old_evidence = news.DB_PATH, accept_news.EVIDENCE
        news.DB_PATH = Path(self.temp.name) / "news.sqlite3"
        accept_news.EVIDENCE = Path(self.temp.name) / "acceptance"
        news.initialize()
        for source, domain in (("nasa", "nasa.gov"), ("esa", "esa.int")):
            for number in range(5):
                records, _ = news.parse_feed(source, rss(domain=domain, query=f"id={number}"))
                news.store_records(records)
            news.update_source(source, success=True, count=5)

    def tearDown(self):
        news.DB_PATH, accept_news.EVIDENCE = self.old_db, self.old_evidence
        self.temp.cleanup()

    def test_failure_preserves_history_and_restores_metadata(self):
        states = news.sources_status()
        with patch.dict(os.environ, {"COLLECT_ENABLED": "0"}), TestClient(app) as client:
            def local_api(path):
                response = client.get(path)
                if response.status_code >= 400:
                    raise urllib.error.HTTPError(path, response.status_code, "test", {}, None)
                return response.json()

            class Homepage(BytesIO):
                status = 200

            with patch.object(accept_news, "api", side_effect=local_api), patch.object(
                    accept_news.urllib.request, "urlopen", side_effect=lambda *args, **kw: Homepage(b"news-ui.js")):
                result = asyncio.run(accept_news.failure_check())
                self.assertEqual(result["history_readable"], {"all": 10, "nasa": 5, "esa": 5})
        self.assertEqual(news.sources_status(), states)

    def test_rebuild_evidence_accepts_preserved_identities(self):
        accept_news.EVIDENCE.mkdir()
        (accept_news.EVIDENCE / "before.json").write_text(json.dumps({"baseline": accept_news.identities()}))
        with patch.object(accept_news.sys, "argv", ["accept_news", "after"]), patch.object(
                accept_news, "check_api", return_value={"all": 10}), patch("builtins.print"):
            accept_news.main()
        self.assertEqual(json.loads((accept_news.EVIDENCE / "result.json").read_text())["container_recreation"], "passed")

    def test_rebuild_evidence_rejects_lost_history(self):
        accept_news.EVIDENCE.mkdir()
        (accept_news.EVIDENCE / "before.json").write_text(json.dumps({"baseline": accept_news.identities()}))
        with news.connect() as conn:
            conn.execute("DELETE FROM articles WHERE id=(SELECT MIN(id) FROM articles)")
        with patch.object(accept_news.sys, "argv", ["accept_news", "after"]), self.assertRaises(AssertionError):
            accept_news.main()

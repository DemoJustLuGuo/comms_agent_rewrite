"""online_knowledge 工具单元测试。

测试 provider 路由、解析和错误处理；网络调用通过 mock 完成，不依赖外网。
"""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = PROJECT_ROOT / "tools" / "online_knowledge.py"

spec = importlib.util.spec_from_file_location("online_knowledge", TOOL_PATH)
online_knowledge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(online_knowledge)


class OnlineKnowledgeTests(unittest.TestCase):
    def test_rejects_missing_query(self):
        with self.assertRaises(ValueError):
            online_knowledge.handle({"source": "wikidata"})

    def test_wikidata_entity_result(self):
        fake = {
            "search": [
                {
                    "id": "Q176862",
                    "label": "MIMO",
                    "description": "use of multiple antennas in radio",
                }
            ]
        }
        with patch.object(online_knowledge, "fetch_json", return_value=fake):
            out = online_knowledge.handle({"query": "MIMO", "source": "wikidata", "max_results": 1})
        self.assertEqual(out["source"], "wikidata")
        self.assertEqual(out["results"][0]["title"], "MIMO")
        self.assertIn("Q176862", out["results"][0]["url"])

    def test_hf_telecom_kg_filter_result(self):
        fake = {
            "rows": [
                {
                    "row": {
                        "source": "wikidata",
                        "subject_id": "Q176862",
                        "subject_label": "MIMO",
                        "subject_description": "use of multiple antennas in radio",
                        "property_id": "P279",
                        "property_label": "subclass of",
                        "value_id": "Q118093",
                        "value_label": "transmission",
                    }
                }
            ]
        }
        with patch.object(online_knowledge, "fetch_json", return_value=fake):
            out = online_knowledge.handle({"query": "MIMO", "source": "hf_telecom_kg"})
        self.assertEqual(out["source"], "hf_telecom_kg")
        self.assertIn("subclass of", out["results"][0]["title"])
        self.assertEqual(out["results"][0]["metadata"]["subject_id"], "Q176862")

    def test_ietf_rfc_metadata(self):
        fake = {
            "name": "rfc9000",
            "title": "QUIC: A UDP-Based Multiplexed and Secure Transport",
            "group": {"acronym": "quic", "name": "QUIC"},
            "pages": 151,
        }
        with patch.object(online_knowledge, "fetch_json", return_value=fake):
            out = online_knowledge.handle({"query": "RFC9000", "source": "ietf"})
        self.assertEqual(out["results"][0]["metadata"]["rfc"], "9000")
        self.assertIn("QUIC", out["results"][0]["snippet"])

    def test_rfc_text_result(self):
        text = "Request for Comments: 9000\n\nQUIC: A UDP-Based Multiplexed and Secure Transport\n\nAbstract\nThis document defines QUIC."
        with patch.object(online_knowledge, "fetch_text", return_value=text):
            out = online_knowledge.handle({"query": "RFC9000", "source": "rfc"})
        self.assertEqual(out["source"], "rfc")
        self.assertIn("rfc9000.txt", out["results"][0]["url"])
        self.assertIn("QUIC", out["results"][0]["snippet"])

    def test_arxiv_atom_result(self):
        atom = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <published>2024-01-01T00:00:00Z</published>
    <title>Massive MIMO Survey</title>
    <summary>A survey on massive MIMO.</summary>
    <author><name>Alice</name></author>
  </entry>
</feed>
"""
        with patch.object(online_knowledge, "fetch_text", return_value=atom):
            out = online_knowledge.handle({"query": "massive MIMO", "source": "arxiv"})
        self.assertEqual(out["results"][0]["evidence_type"], "paper_preprint")
        self.assertEqual(out["results"][0]["metadata"]["authors"], ["Alice"])

    def test_arxiv_parse_error_returns_provider_error(self):
        with patch.object(online_knowledge, "fetch_text", return_value="<not valid"):
            out = online_knowledge.handle({"query": "massive MIMO", "source": "arxiv"})
        self.assertEqual(out["source"], "arxiv")
        self.assertFalse(out["results"])
        self.assertEqual(out["error"]["stage"], "provider")
        self.assertIn("XML", out["warnings"][0])

    def test_fetch_json_parse_error_is_provider_error(self):
        with patch.object(online_knowledge, "_request", return_value=b"{not json"):
            with self.assertRaises(online_knowledge.ProviderError):
                online_knowledge.fetch_json("https://www.wikidata.org/w/api.php")

    def test_auto_rfc_merges_ietf_and_rfc(self):
        def fake_json(url):
            self.assertIn("rfc9000", url)
            return {"name": "rfc9000", "title": "QUIC", "group": {"acronym": "quic"}, "pages": 151}

        with patch.object(online_knowledge, "fetch_json", side_effect=fake_json), patch.object(
            online_knowledge, "fetch_text", return_value="RFC 9000\n\nQUIC transport"
        ):
            out = online_knowledge.handle({"query": "RFC9000", "source": "auto", "max_results": 5})
        self.assertEqual(out["source"], "auto")
        self.assertEqual(len(out["results"]), 2)

    def test_optional_provider_without_key_is_warning(self):
        with patch.dict("os.environ", {}, clear=True):
            out = online_knowledge.handle({"query": "TS 23.501", "source": "3gpp_scout"})
        self.assertFalse(out["results"])
        self.assertIn("THREEGPP_SCOUT_API_KEY", out["warnings"][0])

    def test_cli_success_json_shape(self):
        fake = {"search": [{"id": "Q1", "label": "Test", "description": "desc"}]}
        with patch.object(online_knowledge, "fetch_json", return_value=fake):
            out = online_knowledge.handle(json.loads('{"query":"Test","source":"wikidata"}'))
        self.assertIn("results", out)
        self.assertIn("warnings", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""在线通信知识源查询工具（被 online_knowledge 工具调用）。

输入：stdin 或 argv[1] 为 JSON，字段：
    query, intent?, source?, max_results?
输出：JSON 字符串，包含 results / warnings / error。

本工具只访问白名单 provider，不接受任意 URL，避免把它变成通用网页抓取器。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_TIMEOUT_S = 15
MAX_RESULTS_LIMIT = 10
USER_AGENT = "comms-agent-online-knowledge/0.1"
ARXIV_MIN_INTERVAL_S = 3.0
_LAST_ARXIV_TS = 0.0

SOURCES = {
    "auto",
    "wikidata",
    "hf_telecom_kg",
    "ietf",
    "rfc",
    "arxiv",
    "3gpp_openapi",
    "3gpp_scout",
    "semantic_scholar",
    "openalex",
    "ieee",
}

INTENTS = {"auto", "term", "protocol", "standard", "paper", "schema"}


class ProviderError(Exception):
    """可恢复 provider 错误。"""


def _read_payload() -> Dict[str, Any]:
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    if not raw.strip():
        raise ValueError("missing JSON payload")
    return json.loads(raw)


def _validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = str(payload.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")
    if len(query) > 300:
        raise ValueError("query must be <= 300 characters")

    source = str(payload.get("source", "auto")).strip() or "auto"
    intent = str(payload.get("intent", "auto")).strip() or "auto"
    if source not in SOURCES:
        raise ValueError(f"unsupported source: {source}")
    if intent not in INTENTS:
        raise ValueError(f"unsupported intent: {intent}")

    max_results = int(payload.get("max_results", 5))
    if max_results < 1 or max_results > MAX_RESULTS_LIMIT:
        raise ValueError(f"max_results must be between 1 and {MAX_RESULTS_LIMIT}")

    return {"query": query, "source": source, "intent": intent, "max_results": max_results}


def _request(url: str, *, headers: Optional[Dict[str, str]] = None) -> bytes:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_S) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ProviderError(str(reason)) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ProviderError("request timed out") from exc
    except OSError as exc:
        raise ProviderError(str(exc)) from exc


def fetch_json(url: str, *, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    try:
        return json.loads(_request(url, headers=headers).decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ProviderError(f"invalid JSON response: {exc}") from exc


def fetch_text(url: str, *, headers: Optional[Dict[str, str]] = None) -> str:
    return _request(url, headers=headers).decode("utf-8", errors="replace")


def _result(title: str, url: str, snippet: str, evidence_type: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "title": title,
        "url": url,
        "snippet": " ".join(str(snippet).split())[:1200],
        "evidence_type": evidence_type,
        "metadata": metadata or {},
    }


def _empty(query: str, intent: str, source: str, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"query": query, "intent": intent, "source": source, "results": [], "warnings": warnings or []}


def _with_error(base: Dict[str, Any], stage: str, message: str) -> Dict[str, Any]:
    base["error"] = {"stage": stage, "message": message}
    return base


def _rfc_number(query: str) -> Optional[str]:
    match = re.search(r"\bRFC\s*[- ]?(\d{1,5})\b", query, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.fullmatch(r"\s*(\d{3,5})\s*", query)
    return match.group(1) if match else None


def query_wikidata(query: str, intent: str, max_results: int) -> Dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "action": "wbsearchentities",
            "search": query,
            "language": "en",
            "format": "json",
            "limit": max_results,
        }
    )
    url = f"https://www.wikidata.org/w/api.php?{params}"
    try:
        data = fetch_json(url)
    except ProviderError as exc:
        return _with_error(_empty(query, intent, "wikidata", [f"Wikidata 查询失败：{exc}"]), "provider", str(exc))

    results = []
    for item in data.get("search", [])[:max_results]:
        qid = item.get("id", "")
        label = item.get("label", qid)
        desc = item.get("description", "")
        results.append(
            _result(
                label,
                f"https://www.wikidata.org/wiki/{qid}" if qid else "https://www.wikidata.org/",
                desc,
                "entity",
                {"id": qid, "license_or_policy": "CC0"},
            )
        )
    out = _empty(query, intent, "wikidata")
    out["results"] = results
    if not results:
        out["warnings"].append("Wikidata 未返回匹配实体。")
    return out


def _hf_quote(value: str) -> str:
    return value.replace("'", "''")


def query_hf_telecom_kg(query: str, intent: str, max_results: int) -> Dict[str, Any]:
    where = f'"subject_label"=\'{_hf_quote(query)}\''
    params = urllib.parse.urlencode(
        {
            "dataset": "PleIAs/telecom-knowledge-base",
            "config": "default",
            "split": "train",
            "where": where,
            "offset": 0,
            "length": max_results,
        }
    )
    url = f"https://datasets-server.huggingface.co/filter?{params}"
    try:
        data = fetch_json(url)
    except ProviderError as exc:
        return _with_error(
            _empty(query, intent, "hf_telecom_kg", [f"Hugging Face telecom KG /filter 查询失败：{exc}"]),
            "provider",
            str(exc),
        )

    results = []
    for row_wrap in data.get("rows", [])[:max_results]:
        row = row_wrap.get("row", {})
        subject = row.get("subject_label", query)
        prop = row.get("property_label", "")
        value = row.get("value_label") or row.get("value_id") or ""
        desc = row.get("subject_description", "")
        snippet = f"{subject}: {desc}. {prop}: {value}".strip()
        qid = row.get("subject_id", "")
        results.append(
            _result(
                f"{subject} - {prop}" if prop else subject,
                f"https://huggingface.co/datasets/PleIAs/telecom-knowledge-base",
                snippet,
                "knowledge_graph_row",
                {
                    "source": row.get("source", ""),
                    "subject_id": qid,
                    "property_id": row.get("property_id", ""),
                    "value_id": row.get("value_id", ""),
                },
            )
        )
    out = _empty(query, intent, "hf_telecom_kg")
    out["results"] = results
    if not results:
        out["warnings"].append("Hugging Face telecom KG 未返回精确 subject_label 匹配。")
    return out


def query_ietf(query: str, intent: str, max_results: int) -> Dict[str, Any]:
    del max_results
    number = _rfc_number(query)
    if not number:
        return _empty(query, intent, "ietf", ["IETF provider 首批仅支持 RFC 编号查询，例如 RFC9000。"])
    url = f"https://datatracker.ietf.org/doc/rfc{number}/doc.json"
    try:
        data = fetch_json(url)
    except ProviderError as exc:
        return _with_error(_empty(query, intent, "ietf", [f"IETF Datatracker 查询失败：{exc}"]), "provider", str(exc))
    group = data.get("group") or {}
    title = data.get("title") or f"RFC{number}"
    snippet = f"{data.get('name', f'rfc{number}')}: {title}. Group: {group.get('acronym') or group.get('name') or 'unknown'}, pages: {data.get('pages', 'unknown')}."
    out = _empty(query, intent, "ietf")
    out["results"] = [
        _result(
            title,
            f"https://datatracker.ietf.org/doc/rfc{number}/",
            snippet,
            "standard_metadata",
            {"rfc": number, "group": group, "pages": data.get("pages")},
        )
    ]
    return out


def query_rfc(query: str, intent: str, max_results: int) -> Dict[str, Any]:
    del max_results
    number = _rfc_number(query)
    if not number:
        return _empty(query, intent, "rfc", ["RFC provider 首批仅支持 RFC 编号查询，例如 RFC9000。"])
    url = f"https://www.rfc-editor.org/rfc/rfc{number}.txt"
    try:
        text = fetch_text(url)
    except ProviderError as exc:
        return _with_error(_empty(query, intent, "rfc", [f"RFC Editor 正文获取失败：{exc}"]), "provider", str(exc))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = f"RFC {number}"
    for idx, line in enumerate(lines[:80]):
        if line.lower() == "abstract" and idx > 0:
            title = lines[idx - 1][:120]
            break
    snippet = "\n".join(lines[:60])
    out = _empty(query, intent, "rfc")
    out["results"] = [_result(title, url, snippet, "standard_text", {"rfc": number})]
    return out


def query_arxiv(query: str, intent: str, max_results: int) -> Dict[str, Any]:
    global _LAST_ARXIV_TS
    elapsed = time.monotonic() - _LAST_ARXIV_TS
    if _LAST_ARXIV_TS and elapsed < ARXIV_MIN_INTERVAL_S:
        time.sleep(ARXIV_MIN_INTERVAL_S - elapsed)
    _LAST_ARXIV_TS = time.monotonic()

    search_query = f'all:"{query}"' if " " in query.strip() else f"all:{query}"
    params = urllib.parse.urlencode(
        {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    url = f"http://export.arxiv.org/api/query?{params}"
    try:
        text = fetch_text(url)
    except ProviderError as exc:
        return _with_error(_empty(query, intent, "arxiv", [f"arXiv API 查询失败：{exc}"]), "provider", str(exc))

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return _with_error(_empty(query, intent, "arxiv", [f"arXiv API 返回 XML 解析失败：{exc}"]), "provider", str(exc))
    results = []
    for entry in root.findall("atom:entry", ns)[:max_results]:
        title = " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split())
        summary = " ".join((entry.findtext("atom:summary", default="", namespaces=ns) or "").split())
        entry_url = entry.findtext("atom:id", default="", namespaces=ns) or "https://arxiv.org/"
        published = entry.findtext("atom:published", default="", namespaces=ns)
        authors = [a.findtext("atom:name", default="", namespaces=ns) for a in entry.findall("atom:author", ns)]
        results.append(
            _result(
                title or entry_url,
                entry_url,
                summary,
                "paper_preprint",
                {"published": published, "authors": [a for a in authors if a]},
            )
        )
    out = _empty(query, intent, "arxiv")
    out["results"] = results
    if not results:
        out["warnings"].append("arXiv 未返回匹配论文。")
    return out


def query_3gpp_openapi(query: str, intent: str, max_results: int) -> Dict[str, Any]:
    del max_results
    out = _empty(query, intent, "3gpp_openapi")
    out["results"] = [
        _result(
            "3GPP 5G Core Network OpenAPI specifications",
            "https://forge.3gpp.org/rep/all/5G_APIs",
            "官方 3GPP 5G Core Network OpenAPI YAML 仓库，适合查询 NF API schema、数据类型、Rel-15 到 Rel-19 API 文件。",
            "schema_index",
            {"provider": "3GPP Forge"},
        ),
        _result(
            "3GPP FTP OpenAPI archive",
            "https://www.3gpp.org/ftp/Specs/archive/OpenAPI/",
            "官方 3GPP OpenAPI 归档入口，适合按 Release 浏览 5G API YAML。",
            "schema_index",
            {"provider": "3GPP FTP"},
        ),
    ]
    out["warnings"].append("首批 3gpp_openapi 只返回官方入口，不做全目录爬取。")
    return out


def query_optional_key_source(query: str, intent: str, source: str, max_results: int) -> Dict[str, Any]:
    del max_results
    env_by_source = {
        "3gpp_scout": "THREEGPP_SCOUT_API_KEY",
        "semantic_scholar": "SEMANTIC_SCHOLAR_API_KEY",
        "ieee": "IEEE_XPLORE_API_KEY",
    }
    env_name = env_by_source.get(source)
    out = _empty(query, intent, source)
    if env_name and not os.environ.get(env_name):
        out["warnings"].append(f"{source} 需要环境变量 {env_name}，当前未设置；本次未联网查询。")
        return out
    out["warnings"].append(f"{source} provider 已规划但首批尚未实现。")
    return out


def _merge(query: str, intent: str, source: str, outputs: List[Dict[str, Any]], max_results: int) -> Dict[str, Any]:
    merged = _empty(query, intent, source)
    for item in outputs:
        merged["results"].extend(item.get("results", []))
        merged["warnings"].extend(item.get("warnings", []))
    merged["results"] = merged["results"][:max_results]
    if not merged["results"]:
        merged["warnings"].append("自动路由未获得可用结果。")
    return merged


def query_auto(query: str, intent: str, max_results: int) -> Dict[str, Any]:
    rfc_num = _rfc_number(query)
    if rfc_num:
        return _merge(query, "protocol" if intent == "auto" else intent, "auto", [query_ietf(query, "protocol", 1), query_rfc(query, "protocol", 1)], max_results)

    lowered = query.lower()
    if any(token in lowered for token in ["3gpp", "rel-", "5g core api"]) or re.search(r"\b(ts|tr)\s*\d", lowered):
        return query_3gpp_openapi(query, "schema" if intent == "auto" else intent, max_results)

    if intent == "paper" or any(token in lowered for token in ["paper", "survey", "latest", "preprint", "论文", "最新研究"]):
        return query_arxiv(query, "paper", max_results)

    return _merge(query, "term" if intent == "auto" else intent, "auto", [query_wikidata(query, "term", max_results), query_hf_telecom_kg(query, "term", max_results)], max_results)


def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    args = _validate(payload)
    query = args["query"]
    source = args["source"]
    intent = args["intent"]
    max_results = args["max_results"]

    if source == "auto":
        return query_auto(query, intent, max_results)
    if source == "wikidata":
        return query_wikidata(query, intent, max_results)
    if source == "hf_telecom_kg":
        return query_hf_telecom_kg(query, intent, max_results)
    if source == "ietf":
        return query_ietf(query, intent, max_results)
    if source == "rfc":
        return query_rfc(query, intent, max_results)
    if source == "arxiv":
        return query_arxiv(query, intent, max_results)
    if source == "3gpp_openapi":
        return query_3gpp_openapi(query, intent, max_results)
    return query_optional_key_source(query, intent, source, max_results)


def main() -> None:
    try:
        result = handle(_read_payload())
    except Exception as exc:
        print(json.dumps({"results": [], "warnings": [], "error": {"stage": "input", "message": str(exc)}}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

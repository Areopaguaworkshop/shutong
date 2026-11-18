"""Public-metadata discovery for the Bibliographer; never acquires full text."""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree

import requests


_SOURCES = {
    "crossref": "https://api.crossref.org/works",
    "openalex": "https://api.openalex.org/works",
    "semantic-scholar": "https://api.semanticscholar.org/graph/v1/paper/search",
    "doaj": "https://doaj.org/api/search/articles",
    "open-library": "https://openlibrary.org/search.json",
}

_CATALOG = [
    {"id": "crossref", "access": "free", "route": "official public metadata API", "implemented": True, "scope": "DOI and scholarly work metadata"},
    {"id": "openalex", "access": "free", "route": "official public metadata API", "implemented": True, "scope": "works and authors"},
    {"id": "semantic-scholar", "access": "free", "route": "official public metadata API", "implemented": True, "scope": "scholarly paper metadata"},
    {"id": "doaj", "access": "free", "route": "official public metadata API", "implemented": True, "scope": "open-access journal articles"},
    {"id": "open-library", "access": "free", "route": "official public metadata API", "implemented": True, "scope": "books and editions"},
    {"id": "catalogue", "access": "varies", "route": "scholar-supplied JSON catalogue endpoint", "implemented": True, "scope": "library catalogue metadata"},
    {"id": "institutional-oai-pmh", "access": "varies", "route": "scholar-supplied OAI-PMH endpoint", "implemented": True, "scope": "institutional repository metadata"},
    {"id": "publisher-metadata", "access": "varies", "route": "scholar-supplied public publisher page", "implemented": True, "scope": "publisher landing-page metadata"},
    {"id": "paid-index", "access": "paid", "route": "credentialed adapter", "implemented": False, "scope": "licensed academic indexes"},
    {"id": "google-scholar", "access": "restricted", "route": "cautious browser adapter", "implemented": False, "scope": "deferred; no bypass of controls"},
]


def source_catalog(_args: dict[str, Any]) -> dict[str, Any]:
    """Expose adapter reach honestly before a Bibliographer chooses a source."""
    return {"status": "ok", "sources": _CATALOG}


def _authors(values: list[dict[str, Any]] | None) -> list[str]:
    return [" ".join(part for part in (value.get("given"), value.get("family")) if part) or value.get("name", "") for value in values or []]


def _entry(source: str, item: dict[str, Any]) -> dict[str, Any]:
    if source == "crossref":
        title = (item.get("title") or [""])[0]
        year = ((item.get("published-print") or item.get("published-online") or {}).get("date-parts") or [[None]])[0][0]
        identifier = item.get("DOI") or item.get("URL") or title
        return {"id": f"crossref:{identifier}", "title": title, "authors": _authors(item.get("author")), "year": year, "doi": item.get("DOI"), "url": item.get("URL"), "provenance": source}
    if source == "openalex":
        identifier = item.get("doi") or item.get("id") or item.get("display_name")
        return {"id": f"openalex:{identifier}", "title": item.get("display_name", ""), "authors": _authors([author.get("author", {}) for author in item.get("authorships", [])]), "year": item.get("publication_year"), "doi": item.get("doi"), "url": item.get("id"), "provenance": source}
    if source == "semantic-scholar":
        external = item.get("externalIds") or {}
        identifier = external.get("DOI") or item.get("paperId") or item.get("title")
        return {"id": f"semantic-scholar:{identifier}", "title": item.get("title", ""), "authors": _authors(item.get("authors")), "year": item.get("year"), "doi": external.get("DOI"), "url": item.get("url"), "provenance": source}
    if source == "doaj":
        bib = item.get("bibjson", {})
        identifier = bib.get("identifier", [{}])[0].get("id") or bib.get("title")
        return {"id": f"doaj:{identifier}", "title": bib.get("title", ""), "authors": _authors(bib.get("author")), "year": bib.get("year"), "url": (bib.get("link") or [{}])[0].get("url"), "provenance": source, "access": {"category": "open", "provenance": "DOAJ metadata"}}
    identifier = item.get("key") or item.get("title")
    return {"id": f"open-library:{identifier}", "title": item.get("title", ""), "authors": item.get("author_name", []), "year": item.get("first_publish_year"), "url": f"https://openlibrary.org{item.get('key', '')}", "provenance": source}


def _fetch(source: str, query: str, limit: int) -> list[dict[str, Any]]:
    if source == "crossref":
        payload = requests.get(_SOURCES[source], params={"query.bibliographic": query, "rows": limit}, timeout=15).json()
        return [_entry(source, item) for item in payload.get("message", {}).get("items", [])]
    if source == "openalex":
        payload = requests.get(_SOURCES[source], params={"search": query, "per-page": limit}, timeout=15).json()
        return [_entry(source, item) for item in payload.get("results", [])]
    if source == "semantic-scholar":
        payload = requests.get(_SOURCES[source], params={"query": query, "limit": limit, "fields": "title,authors,year,externalIds,url"}, timeout=15).json()
        return [_entry(source, item) for item in payload.get("data", [])]
    if source == "doaj":
        payload = requests.get(f"{_SOURCES[source]}/{query}", params={"pageSize": limit}, timeout=15).json()
        return [_entry(source, item) for item in payload.get("results", [])]
    payload = requests.get(_SOURCES[source], params={"q": query, "limit": limit}, timeout=15).json()
    return [_entry(source, item) for item in payload.get("docs", [])]


def _custom_entries(args: dict[str, Any], query: str, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Use only explicitly supplied public endpoints; never acquire source bodies."""
    results, errors = [], []
    for config in args.get("adapters", []):
        if not isinstance(config, dict) or config.get("source") not in {"catalogue", "institutional-oai-pmh", "publisher-metadata"}:
            errors.append({"source": "custom", "error": "invalid adapter configuration"})
            continue
        source, url = config["source"], str(config.get("url", ""))
        if not url.startswith("https://"):
            errors.append({"source": source, "error": "adapter URL must use https"})
            continue
        try:
            if source == "catalogue":
                payload = requests.get(url, params={"q": query, "limit": limit}, timeout=15).json()
                for item in payload.get("docs", payload.get("results", []))[:limit]:
                    title = item.get("title", "")
                    results.append({"id": f"catalogue:{item.get('id') or item.get('identifier') or title}", "title": title, "authors": item.get("authors", item.get("author", [])), "year": item.get("year"), "url": item.get("url", url), "provenance": url})
            elif source == "institutional-oai-pmh":
                text = requests.get(url, params={"verb": "ListRecords", "metadataPrefix": "oai_dc", "set": config.get("set", "")}, timeout=15).text
                root = ElementTree.fromstring(text)
                ns = {"dc": "http://purl.org/dc/elements/1.1/"}
                for record in root.findall(".//{*}record")[:limit]:
                    title = record.findtext(".//dc:title", default="", namespaces=ns)
                    identifier = record.findtext(".//dc:identifier", default=title, namespaces=ns)
                    results.append({"id": f"oai:{identifier}", "title": title, "authors": [node.text for node in record.findall(".//dc:creator", ns) if node.text], "year": record.findtext(".//dc:date", default="", namespaces=ns), "url": identifier, "provenance": url})
            else:
                text = requests.get(url, timeout=15).text
                def meta(name: str) -> str:
                    match = __import__("re").search(rf'<meta[^>]+(?:name|property)=["\']{name}["\'][^>]+content=["\']([^"\']+)', text, __import__("re").I)
                    return match.group(1) if match else ""
                title = meta("citation_title") or meta("DC.Title")
                results.append({"id": f"publisher:{url}", "title": title or url, "authors": [meta("citation_author")] if meta("citation_author") else [], "year": meta("citation_publication_date"), "url": url, "provenance": url})
        except (requests.RequestException, ValueError, ElementTree.ParseError) as exc:
            errors.append({"source": source, "error": str(exc)})
    return results, errors


def search_public_metadata(args: dict[str, Any]) -> dict[str, Any]:
    """Search allowed public metadata APIs and retain each source's provenance/error."""
    query = args["query"].strip()
    selected = args.get("sources") or list(_SOURCES)
    limit = min(max(int(args.get("per_source", 10)), 1), 50)
    results, errors, seen = [], [], set()
    for source in selected:
        if source not in _SOURCES:
            errors.append({"source": source, "error": "unsupported source"})
            continue
        try:
            for entry in _fetch(source, query, limit):
                key = (entry.get("doi") or entry["title"]).casefold()
                if key and key not in seen:
                    seen.add(key)
                    results.append(entry)
        except requests.RequestException as exc:
            errors.append({"source": source, "error": str(exc)})
    custom, custom_errors = _custom_entries(args, query, limit)
    for entry in custom:
        key = (entry.get("doi") or entry["title"]).casefold()
        if key and key not in seen:
            seen.add(key)
            results.append(entry)
    return {"status": "ok", "query": query, "entries": results, "errors": errors + custom_errors, "sources": selected}

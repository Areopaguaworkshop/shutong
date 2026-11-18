from shutong_backend.tools import bibliography


def test_public_metadata_search_keeps_provenance_and_source_errors(monkeypatch):
    def fetch(source, query, limit):
        assert query == "Nicene theology"
        assert limit == 2
        if source == "crossref":
            return [{"id": "crossref:doi", "title": "A Work", "doi": "doi", "provenance": source}]
        raise bibliography.requests.RequestException("unavailable")

    monkeypatch.setattr(bibliography, "_fetch", fetch)
    result = bibliography.search_public_metadata({"query": "Nicene theology", "sources": ["crossref", "openalex"], "per_source": 2})
    assert result["entries"] == [{"id": "crossref:doi", "title": "A Work", "doi": "doi", "provenance": "crossref"}]
    assert result["errors"] == [{"source": "openalex", "error": "unavailable"}]


def test_source_catalog_does_not_claim_planned_adapters_are_available():
    sources = {item["id"]: item for item in bibliography.source_catalog({})["sources"]}
    assert sources["crossref"]["implemented"] is True
    assert sources["google-scholar"]["implemented"] is False

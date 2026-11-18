const SOURCES: Record<string, string> = {
  crossref: "https://api.crossref.org/works",
  openalex: "https://api.openalex.org/works",
  "semantic-scholar": "https://api.semanticscholar.org/graph/v1/paper/search",
  doaj: "https://doaj.org/api/search/articles",
  "open-library": "https://openlibrary.org/search.json",
};

const CATALOG = [
  { id: "crossref", access: "free", route: "official public metadata API", implemented: true, scope: "DOI and scholarly work metadata" },
  { id: "openalex", access: "free", route: "official public metadata API", implemented: true, scope: "works and authors" },
  { id: "semantic-scholar", access: "free", route: "official public metadata API", implemented: true, scope: "scholarly paper metadata" },
  { id: "doaj", access: "free", route: "official public metadata API", implemented: true, scope: "open-access journal articles" },
  { id: "open-library", access: "free", route: "official public metadata API", implemented: true, scope: "books and editions" },
  { id: "catalogue", access: "varies", route: "scholar-supplied JSON catalogue endpoint", implemented: false, scope: "deferred in the first TypeScript slice" },
  { id: "institutional-oai-pmh", access: "varies", route: "scholar-supplied OAI-PMH endpoint", implemented: false, scope: "deferred in the first TypeScript slice" },
  { id: "publisher-metadata", access: "varies", route: "scholar-supplied public publisher page", implemented: false, scope: "deferred in the first TypeScript slice" },
  { id: "paid-index", access: "paid", route: "credentialed adapter", implemented: false, scope: "licensed academic indexes" },
  { id: "google-scholar", access: "restricted", route: "cautious browser adapter", implemented: false, scope: "deferred; no bypass of controls" },
];

function authors(values: Array<Record<string, any>> | undefined): string[] {
  return (values ?? []).map((value) =>
    [value?.given, value?.family].filter(Boolean).join(" ") || String(value?.name ?? ""),
  );
}

function entry(source: string, item: Record<string, any>): Record<string, unknown> {
  if (source === "crossref") {
    const title = item.title?.[0] ?? "";
    const year = (item["published-print"] ?? item["published-online"])?.["date-parts"]?.[0]?.[0] ?? null;
    const identifier = item.DOI ?? item.URL ?? title;
    return { id: `crossref:${identifier}`, title, authors: authors(item.author), year, doi: item.DOI, url: item.URL, provenance: source };
  }
  if (source === "openalex") {
    const identifier = item.doi ?? item.id ?? item.display_name;
    return { id: `openalex:${identifier}`, title: item.display_name ?? "", authors: authors((item.authorships ?? []).map((a: any) => a.author ?? {})), year: item.publication_year ?? null, doi: item.doi, url: item.id, provenance: source };
  }
  if (source === "semantic-scholar") {
    const external = item.externalIds ?? {};
    const identifier = external.DOI ?? item.paperId ?? item.title;
    return { id: `semantic-scholar:${identifier}`, title: item.title ?? "", authors: authors(item.authors), year: item.year ?? null, doi: external.DOI, url: item.url, provenance: source };
  }
  if (source === "doaj") {
    const bib = item.bibjson ?? {};
    const identifier = bib.identifier?.[0]?.id ?? bib.title;
    return { id: `doaj:${identifier}`, title: bib.title ?? "", authors: authors(bib.author), year: bib.year ?? null, url: bib.link?.[0]?.url, provenance: source, access: { category: "open", provenance: "DOAJ metadata" } };
  }
  const identifier = item.key ?? item.title;
  return { id: `open-library:${identifier}`, title: item.title ?? "", authors: item.author_name ?? [], year: item.first_publish_year ?? null, url: `https://openlibrary.org${item.key ?? ""}`, provenance: source };
}

async function fetchJson(url: string): Promise<any> {
  const response = await fetch(url, {
    headers: { "user-agent": "shutong-mcp/0.1 (+https://github.com/Areopaguaworkshop/shutong)" },
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function fetchSource(source: string, query: string, limit: number): Promise<Array<Record<string, unknown>>> {
  switch (source) {
    case "crossref": {
      const url = `${SOURCES.crossref}?query.bibliographic=${encodeURIComponent(query)}&rows=${limit}`;
      const payload = await fetchJson(url);
      return (payload?.message?.items ?? []).map((item: any) => entry(source, item));
    }
    case "openalex": {
      const url = `${SOURCES.openalex}?search=${encodeURIComponent(query)}&per-page=${limit}`;
      const payload = await fetchJson(url);
      return (payload?.results ?? []).map((item: any) => entry(source, item));
    }
    case "semantic-scholar": {
      const url = `${SOURCES["semantic-scholar"]}?query=${encodeURIComponent(query)}&limit=${limit}&fields=title,authors,year,externalIds,url`;
      const payload = await fetchJson(url);
      return (payload?.data ?? []).map((item: any) => entry(source, item));
    }
    case "doaj": {
      const url = `${SOURCES.doaj}/${encodeURIComponent(query)}?pageSize=${limit}`;
      const payload = await fetchJson(url);
      return (payload?.results ?? []).map((item: any) => entry(source, item));
    }
    case "open-library": {
      const url = `${SOURCES["open-library"]}?q=${encodeURIComponent(query)}&limit=${limit}`;
      const payload = await fetchJson(url);
      return (payload?.docs ?? []).map((item: any) => entry(source, item));
    }
    default:
      throw new Error("unsupported source");
  }
}

export async function handleBibliography(args: {
  action?: string;
  query?: string;
  sources?: string[];
  per_source?: number;
  adapters?: Array<Record<string, unknown>>;
}): Promise<Record<string, unknown>> {
  if (args.action === "source_catalog" || args.action === "catalog") {
    return { status: "ok", sources: CATALOG };
  }
  if (args.action !== "search") {
    return {
      status: "error",
      error_code: "invalid_action",
      message: `Unknown bibliography action: ${args.action ?? ""}`,
      next_action: "Use action=search or action=source_catalog.",
    };
  }

  const query = String(args.query ?? "").trim();
  if (!query) {
    return { status: "error", error_code: "invalid_input", message: "query is required" };
  }
  const selected = args.sources?.length ? args.sources : Object.keys(SOURCES);
  const limit = Math.max(1, Math.min(50, Number(args.per_source ?? 10) || 10));
  const results: Array<Record<string, unknown>> = [];
  const errors: Array<Record<string, string>> = [];
  const seen = new Set<string>();

  for (const source of selected) {
    try {
      for (const item of await fetchSource(source, query, limit)) {
        const key = String(item.doi ?? item.title ?? "").toLowerCase();
        if (!key || seen.has(key)) continue;
        seen.add(key);
        results.push(item);
      }
    } catch (error) {
      errors.push({ source, error: (error as Error).message });
    }
  }
  if (Array.isArray(args.adapters) && args.adapters.length > 0) {
    errors.push({ source: "custom", error: "custom adapters are deferred in this slice" });
  }
  return { status: "ok", query, entries: results, errors, sources: selected };
}

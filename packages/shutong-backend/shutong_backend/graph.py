"""Knowledge Graph — build and query a graph from claims, sources, and contradictions."""

import json
import os
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional

from .agents.models import SCHEMA_VERSION


@dataclass
class GraphNode:
    node_id: str = ""
    label: str = ""
    node_type: str = ""  # claim | source | concept | author
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GraphEdge:
    edge_id: str = ""
    source: str = ""  # node_id
    target: str = ""  # node_id
    edge_type: str = ""  # supports | contradicts | cites | relates_to | authored_by
    weight: float = 1.0
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KnowledgeGraph:
    """In-memory + persisted graph from claims, sources, and contradictions."""

    def __init__(self, graph_dir: str = "", schema_version: str = SCHEMA_VERSION) -> None:
        self.graph_dir = graph_dir or os.path.join("corpus", ".shutong", "graph")
        self.schema_version = schema_version
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self._load()

    def add_node(self, node_id: str, label: str, node_type: str, properties: Optional[Dict[str, Any]] = None) -> None:
        self.nodes[node_id] = {"node_id": node_id, "label": label, "node_type": node_type, "properties": properties or {}}

    def add_edge(self, source_id: str, target_id: str, edge_type: str, weight: float = 1.0, properties: Optional[Dict[str, Any]] = None) -> None:
        edge_id = f"{source_id}-{edge_type}-{target_id}"
        self.edges.append({"edge_id": edge_id, "source": source_id, "target": target_id, "edge_type": edge_type, "weight": weight, "properties": properties or {}})

    def add_claims(self, claims: List[Dict[str, Any]]) -> None:
        for claim in claims:
            claim_id = claim.get("claim_id", f"claim-{len(self.nodes)}")
            self.add_node(node_id=claim_id, label=claim.get("claim_text", "")[:80], node_type="claim", properties={"polarity": claim.get("polarity_tag", "neutral"), "section_ref": claim.get("section_ref", "")})

    def add_contradictions(self, contradictions: List[Dict[str, Any]]) -> None:
        for c in contradictions:
            self.add_edge(source_id=c.get("claim_a_id", ""), target_id=c.get("claim_b_id", ""), edge_type="contradicts", weight=0.8)

    def add_source(self, source_id: str, title: str, authors: List[str] = None) -> None:
        self.add_node(node_id=source_id, label=title, node_type="source", properties={"authors": authors or []})

    def query(self, node_id: str, depth: int = 2) -> Dict[str, Any]:
        if node_id not in self.nodes:
            return {"nodes": [], "edges": []}
        visited_nodes = {node_id}
        visited_edges = set()
        frontier = {node_id}
        for _ in range(depth):
            next_frontier = set()
            for nid in frontier:
                for edge in self.edges:
                    if edge["source"] == nid:
                        visited_edges.add(edge["edge_id"])
                        if edge["target"] in self.nodes:
                            visited_nodes.add(edge["target"])
                            next_frontier.add(edge["target"])
                    elif edge["target"] == nid:
                        visited_edges.add(edge["edge_id"])
                        if edge["source"] in self.nodes:
                            visited_nodes.add(edge["source"])
                            next_frontier.add(edge["source"])
            frontier = next_frontier
        return {"nodes": [self.nodes[nid] for nid in visited_nodes if nid in self.nodes], "edges": [e for e in self.edges if e["edge_id"] in visited_edges]}

    def stats(self) -> Dict[str, int]:
        return {"nodes": len(self.nodes), "edges": len(self.edges), "claims": sum(1 for n in self.nodes.values() if n["node_type"] == "claim"), "sources": sum(1 for n in self.nodes.values() if n["node_type"] == "source"), "contradictions": sum(1 for e in self.edges if e["edge_type"] == "contradicts")}

    def save(self) -> None:
        os.makedirs(self.graph_dir, exist_ok=True)
        with open(os.path.join(self.graph_dir, "graph.json"), "w") as f:
            json.dump({"nodes": list(self.nodes.values()), "edges": self.edges, "schema_version": self.schema_version}, f, indent=2)

    def _load(self) -> None:
        path = os.path.join(self.graph_dir, "graph.json")
        if not os.path.exists(path):
            return
        with open(path) as f:
            data = json.load(f)
        for node in data.get("nodes", []):
            self.nodes[node["node_id"]] = node
        self.edges = data.get("edges", [])
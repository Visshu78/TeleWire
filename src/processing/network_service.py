import networkx as nx
import logging

logger = logging.getLogger(__name__)


class NetworkAnalyzer:
    def __init__(self, db_handler):
        self.db = db_handler

    def get_cytoscape_graph(self, fetched_by=None) -> dict:
        """
        Builds a directed network graph using NetworkX, computes centralities,
        and formats the output for Cytoscape.js visualization.
        """
        relationships = self.db.get_forward_relationships(fetched_by=fetched_by)
        
        # Build DiGraph
        G = nx.DiGraph()
        
        # Keep track of names for labels
        node_labels = {}
        node_types = {}  # "source" (forwarded channel) or "target" (ingested group)
        
        for rel in relationships:
            src_id = f"c_{rel['source_id']}"
            src_name = rel['source_name'] or f"Channel {rel['source_id']}"
            tgt_id = f"g_{rel['target_id']}"
            tgt_name = rel['target_name'] or f"Group {rel['target_id']}"
            weight = rel['forward_count']
            
            node_labels[src_id] = src_name
            node_types[src_id] = "source"
            
            node_labels[tgt_id] = tgt_name
            node_types[tgt_id] = "target"
            
            G.add_edge(src_id, tgt_id, weight=weight)
            
        if not G.nodes:
            return {"elements": []}
            
        # Compute centralities
        # PageRank (handles weights and directionality)
        try:
            pagerank = nx.pagerank(G, weight="weight")
        except Exception as exc:
            logger.warning("PageRank calculation failed: %s", exc)
            # Default fallback score
            pagerank = {node: 1.0 / len(G.nodes) for node in G.nodes}
            
        # Degree centralities
        in_degrees = dict(G.in_degree())
        out_degrees = dict(G.out_degree())
        
        # Build Cytoscape elements list
        elements = []
        
        # Add Nodes
        for node in G.nodes:
            pr = pagerank.get(node, 0.0)
            indeg = in_degrees.get(node, 0)
            outdeg = out_degrees.get(node, 0)
            label = node_labels.get(node, node)
            ntype = node_types.get(node, "unknown")
            
            elements.append({
                "data": {
                    "id": node,
                    "label": label,
                    "type": ntype,
                    "pagerank": float(pr),
                    "indegree": int(indeg),
                    "outdegree": int(outdeg)
                }
            })
            
        # Add Edges
        for u, v, data in G.edges(data=True):
            elements.append({
                "data": {
                    "id": f"e_{u}_{v}",
                    "source": u,
                    "target": v,
                    "weight": int(data.get("weight", 1))
                }
            })
            
        return {"elements": elements}

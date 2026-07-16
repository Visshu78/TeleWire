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

    def get_entity_connection_graph(self, fetched_by=None) -> dict:
        """
        Builds a node-link diagram mapping actors, monitored groups, and
        highly relevant threat IOCs (crypto addresses, phone numbers, UPIs).
        Filters out low-degree outliers to focus strictly on coordinated actors.
        """
        relations = self.db.get_entity_relationships(fetched_by=fetched_by)
        
        G = nx.Graph()
        
        node_labels = {}
        node_types = {}
        entity_types = {}
        
        allowed_types = {"crypto_btc", "crypto_eth", "crypto_tron", "crypto_ton", "phone_number", "upi_id", "email"}
        
        for rel in relations:
            etype = rel["entity_type"]
            if etype not in allowed_types:
                continue
                
            actor_id = f"actor_{rel['sender_id'] or rel['sender_name']}"
            actor_label = f"{rel['sender_name']} ({rel['sender_id'] or '?'})"
            
            group_id = f"group_{rel['group_id']}"
            group_label = rel["group_name"] or f"Group {rel['group_id']}"
            
            ent_id = f"entity_{rel['entity_id']}"
            ent_label = rel["entity_value"]
            
            # Save node details
            node_labels[actor_id] = actor_label
            node_types[actor_id] = "actor"
            
            node_labels[group_id] = group_label
            node_types[group_id] = "group"
            
            node_labels[ent_id] = ent_label
            node_types[ent_id] = "entity"
            entity_types[ent_id] = etype
            
            # Add relationships
            G.add_edge(actor_id, ent_id)
            G.add_edge(actor_id, group_id)
            
        if not G.nodes:
            return {"elements": []}
            
        # Top coordination check to prevent UI layout freezing
        if len(G.nodes) > 300:
            core_nodes = [node for node, deg in G.degree() if deg >= 2]
            if len(core_nodes) < 50:
                core_nodes = sorted(G.nodes, key=lambda n: G.degree(n), reverse=True)[:150]
            G = G.subgraph(core_nodes).copy()
            
        elements = []
        for node in G.nodes:
            label = node_labels.get(node, node)
            ntype = node_types.get(node, "unknown")
            etype = entity_types.get(node, "")
            
            elements.append({
                "data": {
                    "id": node,
                    "label": label,
                    "type": ntype,
                    "entity_type": etype,
                    "pagerank": 0.05, # Uniform sizing indicator for entities/actors
                }
            })
            
        for u, v in G.edges():
            elements.append({
                "data": {
                    "id": f"e_{u}_{v}",
                    "source": u,
                    "target": v,
                    "weight": 1
                }
            })
            
        return {"elements": elements}


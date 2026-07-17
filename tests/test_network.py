import unittest
import os
import shutil
import tempfile

from src.storage.database import init_db, DatabaseHandler
from src.processing.network_service import NetworkAnalyzer


class TestNetworkIntelligence(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_network_db.db")
        init_db(self.db_path)
        self.db = DatabaseHandler(self.db_path)

        # Seed groups
        self.db.upsert_group(901, "Target Group A", "supergroup", 100)
        self.db.upsert_group(902, "Target Group B", "supergroup", 250)

        # Seed messages with forwards
        # Source 111 forwards 3 times to Group 901
        # Source 222 forwards 1 time to Group 901, and 2 times to Group 902
        self.messages = [
            # forwards from 111 -> 901
            self._msg(1, 901, "Target Group A", "Alice", 1, "Channel 111", 111, "2026-07-03T10:15:30+00:00", "h1"),
            self._msg(2, 901, "Target Group A", "Alice", 1, "Channel 111", 111, "2026-07-03T10:45:00+00:00", "h2"),
            self._msg(3, 901, "Target Group A", "Alice", 1, "Channel 111", 111, "2026-07-03T11:20:00+00:00", "h3"),
            # forwards from 222 -> 901
            self._msg(4, 901, "Target Group A", "Bob", 1, "Channel 222", 222, "2026-07-03T10:30:00+00:00", "h4"),
            # forwards from 222 -> 902
            self._msg(5, 902, "Target Group B", "Bob", 1, "Channel 222", 222, "2026-07-03T20:10:00+00:00", "h5"),
            self._msg(6, 902, "Target Group B", "Bob", 1, "Channel 222", 222, "2026-07-03T20:55:00+00:00", "h6"),
            # non-forwarded message in 901
            self._msg(7, 901, "Target Group A", "Charlie", 0, None, None, "2026-07-03T22:00:00+00:00", "h7"),
        ]
        self.db.insert_messages_batch(self.messages)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _msg(self, msg_id, grp_id, grp_name, sender, is_fwd, fwd_name, fwd_id, timestamp, msg_hash):
        return {
            "message_id": msg_id,
            "group_id": grp_id,
            "group_name": grp_name,
            "sender_name": sender,
            "sender_phone": None,
            "text": "test text",
            "language": "en",
            "is_forwarded": is_fwd,
            "forward_from_name": fwd_name,
            "forward_from_id": fwd_id,
            "matched_keyword": None,
            "fuzzy_score": 0.0,
            "is_matched": 0,
            "timestamp": timestamp,
            "hash": msg_hash
        }

    def test_get_forward_relationships(self):
        rels = self.db.get_forward_relationships()
        self.assertEqual(len(rels), 3) # (111 -> 901), (222 -> 901), (222 -> 902)
        
        # Check mapping
        counts = {(r["source_id"], r["target_id"]): r["forward_count"] for r in rels}
        self.assertEqual(counts.get((111, 901)), 3)
        self.assertEqual(counts.get((222, 901)), 1)
        self.assertEqual(counts.get((222, 902)), 2)

    def test_get_temporal_distribution(self):
        # Global distribution
        dist = self.db.get_temporal_distribution()
        # Hours active: 10 (3 messages: msg 1,2,4), 11 (1 message: msg 3), 20 (2 messages: msg 5,6), 22 (1 message: msg 7)
        hours = {d["hour"]: d["msg_count"] for d in dist}
        self.assertEqual(hours.get("10"), 3)
        self.assertEqual(hours.get("11"), 1)
        self.assertEqual(hours.get("20"), 2)
        self.assertEqual(hours.get("22"), 1)

        # Group 902 distribution
        dist_902 = self.db.get_temporal_distribution(902)
        hours_902 = {d["hour"]: d["msg_count"] for d in dist_902}
        self.assertEqual(hours_902.get("20"), 2)
        self.assertNotIn("10", hours_902)

    def test_network_analyzer_output(self):
        analyzer = NetworkAnalyzer(self.db)
        res = analyzer.get_cytoscape_graph()
        self.assertIn("elements", res)
        elements = res["elements"]

        nodes = [e for e in elements if "type" in e["data"]]
        edges = [e for e in elements if "source" in e["data"]]

        # Nodes: c_111, c_222, g_901, g_902 -> 4 nodes
        self.assertEqual(len(nodes), 4)
        self.assertEqual(len(edges), 3)

        # Check types
        node_types = {n["data"]["id"]: n["data"]["type"] for n in nodes}
        self.assertEqual(node_types["c_111"], "source")
        self.assertEqual(node_types["g_901"], "target")

        # Verify PageRank and degrees are present
        for node in nodes:
            self.assertIn("pagerank", node["data"])
            self.assertIn("indegree", node["data"])
            self.assertIn("outdegree", node["data"])
            
        # Target group 901 should have in-degree 2 (receives from 111 and 222)
        g_901_node = next(n for n in nodes if n["data"]["id"] == "g_901")
        self.assertEqual(g_901_node["data"]["indegree"], 2)

    def test_settings_get_set(self):
        self.db.set_setting("test_key", "test_val")
        self.assertEqual(self.db.get_setting("test_key"), "test_val")
        self.assertEqual(self.db.get_setting("non_existent", "default"), "default")

    def test_entity_connection_graph(self):
        # Link entity to message 1 using standard save_message_entities method
        entities_list = [{"type": "crypto_btc", "value": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "position": 0}]
        self.db.save_message_entities(1, entities_list, "2026-07-03T10:15:30+00:00")
        
        analyzer = NetworkAnalyzer(self.db)
        res = analyzer.get_entity_connection_graph()
        self.assertIn("elements", res)
        elements = res["elements"]
        
        nodes = [e for e in elements if "type" in e["data"]]
        edges = [e for e in elements if "source" in e["data"]]
        
        node_types = [n["data"]["type"] for n in nodes]
        self.assertIn("actor", node_types)
        self.assertIn("group", node_types)
        self.assertIn("entity", node_types)
        self.assertGreater(len(edges), 0)

    def test_actor_behavior_fingerprinting(self):
        behavior = self.db.get_actor_behavior("Bob")
        self.assertIsNotNone(behavior)
        self.assertEqual(behavior["group_count"], 2)
        self.assertEqual(behavior["op_mode"], "Human Operator")
        self.assertIn("hour_distribution", behavior)
        self.assertIn("timezone_inference", behavior)

    def test_geocoding_ip_and_phone(self):
        entities_list = [{"type": "phone_number", "value": "+919999999999", "position": 0}]
        self.db.save_message_entities(1, entities_list, "2026-07-03T10:15:30+00:00")
        
        from src.processing.geocoding_service import GeocodingService
        geocoder = GeocodingService(self.db)
        
        from src.storage.database import get_db as test_get_db
        with test_get_db(self.db.db_path) as conn:
            row = conn.execute("SELECT id FROM entities WHERE entity_value = ?", ("+919999999999",)).fetchone()
            
        self.assertIsNotNone(row)
        entity_id = row["id"]
        
        coords = geocoder.geocode_entity(entity_id, "phone_number", "+919999999999")
        self.assertIsNotNone(coords)
        self.assertEqual(coords[2], "India")

        loopback_coords = geocoder._geocode_ip("127.0.0.1")
        self.assertEqual(loopback_coords[0], None)
        self.assertIn("Loopback", loopback_coords[2])

    def test_actor_aliases_and_timeline(self):
        # Seed mock messages from Alice and fraudster sharing an entity
        msg_alice = {
            "message_id": 200, "group_id": 999, "group_name": "Group 999", "sender_name": "Alice",
            "sender_phone": None, "text": "Pay BTC to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "language": "en",
            "is_forwarded": 0, "forward_from_name": None, "forward_from_id": None, "matched_keyword": None,
            "fuzzy_score": 0.0, "is_matched": 0, "timestamp": "2026-07-03T10:15:30+00:00", "hash": "alicehash"
        }
        msg_fraudster = {
            "message_id": 201, "group_id": 999, "group_name": "Group 999", "sender_name": "fraudster",
            "sender_phone": None, "text": "Same wallet here: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "language": "en",
            "is_forwarded": 0, "forward_from_name": None, "forward_from_id": None, "matched_keyword": None,
            "fuzzy_score": 0.0, "is_matched": 0, "timestamp": "2026-07-03T10:17:30+00:00", "hash": "fraudhash"
        }
        self.db.insert_messages_batch([msg_alice, msg_fraudster])
        
        # Look up correct sqlite auto-increment row IDs
        hash_map = self.db.get_message_ids_by_hashes(["alicehash", "fraudhash"])
        alice_row_id = hash_map["alicehash"]
        fraud_row_id = hash_map["fraudhash"]
        
        # Link entities
        self.db.save_message_entities(alice_row_id, [{"type": "crypto_btc", "value": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "position": 11}], "2026-07-03T10:15:30+00:00")
        self.db.save_message_entities(fraud_row_id, [{"type": "crypto_btc", "value": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "position": 17}], "2026-07-03T10:17:30+00:00")
        
        # Verify leak checks lookup
        leak = self.db.lookup_leak_entity("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
        self.assertIsNotNone(leak)
        self.assertIn("Silk Road", leak["source_leak"])
        
        # Verify timeline
        timeline = self.db.get_actor_ioc_timeline("Alice")
        self.assertGreater(len(timeline), 0)
        self.assertEqual(timeline[0]["entity_value"], "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
        
        # Verify suspected aliases linking
        aliases = self.db.get_actor_aliases("Alice")
        self.assertGreater(len(aliases), 0)
        self.assertEqual(aliases[0]["sender_name"], "fraudster")
        self.assertGreaterEqual(aliases[0]["confidence"], 50)
        self.assertIn("Shared Crypto Wallet", aliases[0]["reasons"][0])


if __name__ == "__main__":
    unittest.main()




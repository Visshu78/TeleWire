import os
import json
import uuid
import logging
import numpy as np
from datetime import datetime, timezone
import faiss
from sentence_transformers import SentenceTransformer

from src.storage.database import get_db

logger = logging.getLogger(__name__)

THREAT_CATEGORIES = [
    "Scam/Fraud",
    "Weapons/Violent Extremism",
    "Cybersecurity/Hacking",
    "Financial Crimes/Money Mule",
    "Drug Trafficking",
    "Other/Legitimate"
]

INDEX_PATH = "data/faiss_index.bin"
MAPPING_PATH = "data/faiss_mapping.json"
MODEL_NAME = "all-MiniLM-L6-v2"


class SemanticProcessor:
    _instance = None
    _lock = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(SemanticProcessor, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_handler=None):
        if db_handler is not None:
            self.db = db_handler
        if self._initialized:
            return
        
        logger.info("Initializing SemanticProcessor model %s...", MODEL_NAME)
        # Set cache folder inside project data/models directory
        os.makedirs("data/models", exist_ok=True)
        self.model = SentenceTransformer(MODEL_NAME, cache_folder="data/models")
        self.dimension = 384  # all-MiniLM-L6-v2 outputs 384-dimensional vectors
        
        # Pre-embed category labels for zero-shot classification
        logger.info("Embedding zero-shot threat category labels...")
        descriptive_labels = [
            "This message is related to scams, fraud, phishing, or crypto doubling.",
            "This message is related to weapons, guns, explosives, terrorism, or violence.",
            "This message is related to cybersecurity, hacking, database breach, exploits, or cracking.",
            "This message is related to money mules, financial crimes, money laundering, or bank drop.",
            "This message is related to drug trafficking, buying weed, cocaine, narcotics, or illegal drugs.",
            "This message is a normal chat conversation, general question, greeting, or legitimate topic."
        ]
        self.category_embeddings = self.model.encode(descriptive_labels, convert_to_numpy=True)
        # L2 normalize category embeddings
        norms = np.linalg.norm(self.category_embeddings, axis=1, keepdims=True)
        self.category_embeddings = self.category_embeddings / np.maximum(norms, 1e-12)
        
        # Load or initialize FAISS index
        self.index = None
        self.index_to_msg_id = [] # List mapping index offset -> message_row_id
        self._load_index()
        self._initialized = True

    def _load_index(self):
        """Load index from disk or create a new one."""
        os.makedirs("data", exist_ok=True)
        if os.path.exists(INDEX_PATH) and os.path.exists(MAPPING_PATH):
            try:
                self.index = faiss.read_index(INDEX_PATH)
                with open(MAPPING_PATH, "r", encoding="utf-8") as f:
                    self.index_to_msg_id = json.load(f)
                logger.info("Loaded FAISS index from disk. Total vectors: %d", self.index.ntotal)
                return
            except Exception as exc:
                logger.error("Failed to load FAISS index, creating new index: %s", exc)
        
        # Create empty Cosine Similarity (Inner Product) Index
        self.index = faiss.IndexFlatIP(self.dimension)
        self.index_to_msg_id = []
        logger.info("Initialized new FAISS index.")

    def _save_index(self):
        """Save index to disk."""
        try:
            faiss.write_index(self.index, INDEX_PATH)
            with open(MAPPING_PATH, "w", encoding="utf-8") as f:
                json.dump(self.index_to_msg_id, f)
        except Exception as exc:
            logger.error("Failed to save FAISS index: %s", exc)

    def classify_zero_shot(self, text: str) -> str:
        """Classify message text into one of the candidate threat categories."""
        if not text.strip():
            return "Other/Legitimate"
        
        try:
            # Embed and L2 normalize query
            emb = self.model.encode(text, convert_to_numpy=True)
            norm = np.linalg.norm(emb)
            if norm < 1e-12:
                return "Other/Legitimate"
            emb_norm = emb / norm
            
            # Compute cosine similarity (dot product since normalized)
            similarities = np.dot(self.category_embeddings, emb_norm)
            best_idx = int(np.argmax(similarities))
            return THREAT_CATEGORIES[best_idx]
        except Exception as exc:
            logger.error("classify_zero_shot failed: %s", exc)
            return "Other/Legitimate"

    def process_message_semantics(self, message_row_id: int, text: str, timestamp: str) -> tuple[str, str]:
        """
        Evaluate message text:
          1. Classifies it using zero-shot.
          2. Clusters it using near-duplicate FAISS lookup (threshold >= 0.85).
          3. Upserts campaign metadata and updates the message table.
        Returns a tuple: (campaign_id, threat_category)
        """
        # 1. Zero-shot threat category
        threat_cat = self.classify_zero_shot(text)
        
        if not text.strip():
            # Treat empty/media messages as standard
            return "", threat_cat

        try:
            # 2. Embed message and normalize
            emb = self.model.encode(text, convert_to_numpy=True)
            norm = np.linalg.norm(emb)
            if norm < 1e-12:
                return "", threat_cat
            emb_norm = emb / norm
            
            # Reshape for FAISS (needs float32, 2D array [1, dimension])
            vector = np.array([emb_norm], dtype=np.float32)
            
            campaign_id = None
            
            # 3. FAISS Query
            if self.index.ntotal > 0:
                # Search closest neighbor
                D, I = self.index.search(vector, 1)
                best_score = float(D[0][0])
                best_idx = int(I[0][0])
                
                # Check threshold (cosine similarity >= 0.85)
                if best_score >= 0.85 and best_idx != -1 and best_idx < len(self.index_to_msg_id):
                    matched_msg_id = self.index_to_msg_id[best_idx]
                    # Lookup campaign ID of the matched message from DB
                    try:
                        with get_db(self.db.db_path) as conn:
                            campaign_row = conn.execute(
                                "SELECT campaign_id, timestamp FROM messages WHERE id=?", 
                                (matched_msg_id,)
                            ).fetchone()
                    except Exception as exc:
                        logger.error("Failed to query campaign for matched message %d: %s", matched_msg_id, exc)
                        campaign_row = None
                            
                    if campaign_row and campaign_row["campaign_id"]:
                        campaign_id = campaign_row["campaign_id"]
                        # Update campaign duration bounds in database
                        # Campaign details: update last_seen_at if this msg is newer
                        camp_first_seen = campaign_row["timestamp"]
                        camp_last_seen = timestamp
                        
                        self.db.upsert_campaign(
                            campaign_id=campaign_id,
                            name=f"Campaign {campaign_id[:8].upper()} ({threat_cat})",
                            first_seen=camp_first_seen,
                            last_seen=camp_last_seen,
                            threat_category=threat_cat,
                            rep_text=text[:150]
                        )
            
            # 4. If no campaign matches, spawn a new campaign
            if not campaign_id:
                campaign_id = f"camp_{uuid.uuid4().hex}"
                campaign_name = f"Campaign {campaign_id[5:13].upper()} ({threat_cat})"
                self.db.upsert_campaign(
                    campaign_id=campaign_id,
                    name=campaign_name,
                    first_seen=timestamp,
                    last_seen=timestamp,
                    threat_category=threat_cat,
                    rep_text=text[:150]
                )
            
            # 5. Add vector to FAISS index to enable future duplicates to map to this message
            self.index.add(vector)
            self.index_to_msg_id.append(message_row_id)
            self._save_index()
            
            # 6. Update message row with campaign details
            self.db.update_message_semantic_info(message_row_id, campaign_id, threat_cat)
            
            return campaign_id, threat_cat
            
        except Exception as exc:
            logger.error("process_message_semantics failed for message %d: %s", message_row_id, exc)
            return "", threat_cat

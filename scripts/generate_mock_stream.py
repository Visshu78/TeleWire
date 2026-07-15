import sys
import os
import time
import random
import argparse
from datetime import datetime, timezone

# Add root to python path to resolve modules correctly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.storage.database import DatabaseHandler, init_db
from src.processing import ProcessingEngine
from src.processing.scoring_service import calculate_risk_score, dispatch_alerts

MOCK_SENDERS = [
    {"name": "ShadowAgent", "phone": "+919876543210", "id": 123456701},
    {"name": "MuleBroker_99", "phone": "+919999988888", "id": 123456702},
    {"name": "TraderJoe", "phone": None, "id": 123456703},
    {"name": "SilentBob", "phone": "+919000011111", "id": 123456704},
    {"name": "AlphaHacker", "phone": None, "id": 123456705},
    {"name": "AnonOperator", "phone": None, "id": 123456706}
]

MOCK_GROUPS = [
    {"id": 10001, "name": "Underground Trade Central", "type": "group"},
    {"id": 10002, "name": "Crypto Money Laundering Hub", "type": "channel"},
    {"id": 10003, "name": "Weapons and Mule Exchange", "type": "group"},
    {"id": 10004, "name": "Legitimate Chat Zone", "type": "group"}
]

MOCK_TEMPLATES = [
    # Weapons
    "Selling military grade weapons catalog now. Contact ShadowAgent for prices. Fast shipping.",
    "AK47 rifle and pistol stocks available. Secure drops inside target cities.",
    # Mule/Financial
    "URGENT: Need Indian money mule bank accounts for UPI cashouts. Payouts up to 50,000 INR. pay@okaxis",
    "Fresh bank login logs and carding methods. 100% working. UPI address: transfer@ybl",
    # Drugs
    "High quality drugs available. Overnight delivery. Contact TraderJoe.",
    "Cocaine and mdma shipments arrived. Stealth packaging.",
    # Wallets
    "Send payments to BTC address: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa ASAP.",
    "ETH payouts sent to 0x71C7656EC7ab88b098defB751B7401B5f6d8976F immediately.",
    # Benign
    "Hey guys, what time is the meeting tomorrow?",
    "Can someone help me with this Python script error?",
    "Check out this cool repository link."
]


def generate_mock_message(message_id: int) -> dict:
    group = random.choice(MOCK_GROUPS)
    sender = random.choice(MOCK_SENDERS)
    text = random.choice(MOCK_TEMPLATES)
    
    is_fwd = random.choice([0, 1])
    fwd_name = f"ForwardedSource_{random.randint(1,10)}" if is_fwd else None
    fwd_id = random.randint(50000, 99999) if is_fwd else None
    
    return {
        "message_id": message_id,
        "group_id": group["id"],
        "group_name": group["name"],
        "sender_name": sender["name"],
        "sender_phone": sender["phone"],
        "sender_id": str(sender["id"]),
        "text": text,
        "is_forwarded": is_fwd,
        "forward_from_name": fwd_name,
        "forward_from_id": fwd_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def main():
    parser = argparse.ArgumentParser(description="Simulate real-time Telegram SOCMINT stream.")
    parser.add_argument("--db", default="data/telegram_intel.db", help="Path to database file")
    parser.add_argument("--delay", type=float, default=3.0, help="Delay between messages in seconds")
    parser.add_argument("--count", type=int, default=0, help="Number of messages to ingest (0 = infinite)")
    args = parser.parse_args()

    print(f"[*] Initializing Mock Ingestion Sandbox Database at {args.db}...")
    init_db(args.db)
    db = DatabaseHandler(args.db)

    # Upsert groups in database
    for g in MOCK_GROUPS:
        db.upsert_group(g["id"], g["name"], g["type"], member_count=random.randint(100, 5000))

    # Initialize Processing engine
    engine = ProcessingEngine(db, {"fuzzy_threshold": 80})

    msg_id = random.randint(1000, 9999)
    sent_count = 0
    print(f"[*] Sandbox stream active. Generating mock traffic every {args.delay}s. Press Ctrl+C to stop.\n")

    try:
        while True:
            msg_id += 1
            raw = generate_mock_message(msg_id)
            
            # 1. Process ingestion logic
            enriched = engine.process(raw)
            if not enriched:
                continue
            
            # 2. Insert into database
            inserted = db.insert_message(enriched)
            if not inserted:
                continue
            
            # 3. Retrieve row ID
            hash_to_row = db.get_message_ids_by_hashes([enriched["hash"]])
            row_id = hash_to_row.get(enriched["hash"])
            
            if row_id:
                # 4. Semantic Matcher campaign aggregation
                combined_sem_text = f"{enriched.get('text', '')}\n{enriched.get('ocr_text', '')}".strip()
                engine.semantic_processor.process_message_semantics(
                    row_id,
                    combined_sem_text,
                    enriched["timestamp"]
                )

                # 5. Save message entities
                if enriched.get("entities"):
                    db.save_message_entities(row_id, enriched["entities"], enriched["timestamp"])
                
                # 6. Fetch fully enriched row to compute exact risk score
                m_db = db.get_message_by_row_id(row_id)
                if m_db:
                    score = calculate_risk_score(m_db)
                    db.update_message_risk_score(row_id, score)
                    
                    # Update rolling sender profiles
                    if enriched.get("sender_name"):
                        db.update_sender_profile(
                            enriched["sender_name"],
                            enriched.get("sender_phone"),
                            score,
                            enriched["timestamp"]
                        )
                    
                    # Dispatch alerts
                    dispatch_alerts(m_db, score)
                    
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Ingested message {msg_id} | Sender: {enriched['sender_name']} | Group: {enriched['group_name']} | Risk: {score:.0f}")
            
            sent_count += 1
            if args.count > 0 and sent_count >= args.count:
                print(f"\n[*] Finished streaming {args.count} mock messages.")
                break
                
            time.sleep(args.delay)
            
    except KeyboardInterrupt:
        print("\n[*] Stopping mock stream generator. Sandbox closed.")


if __name__ == "__main__":
    main()

import json
import urllib.request
import logging
import queue
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class WalletEnricher:
    def __init__(self, db_handler):
        self.db = db_handler
        self.enrich_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def enqueue_address(self, entity_id: int, address: str, entity_type: str, is_sanctioned: int):
        """Enqueue a crypto wallet address for enrichment."""
        self.enrich_queue.put((entity_id, address, entity_type, is_sanctioned))

    def _worker(self):
        """Background thread loop to enrich addresses with rate-limiting respect."""
        logger.info("WalletEnricher background worker started.")
        while True:
            try:
                entity_id, address, etype, is_sanctioned = self.enrich_queue.get()
                try:
                    self._enrich_address(entity_id, address, etype, is_sanctioned)
                except Exception as exc:
                    logger.error("Error enriching address %s: %s", address, exc)
                finally:
                    self.enrich_queue.task_done()
                    # Sleep 2 seconds between lookups to prevent rate limiting
                    time.sleep(2.0)
            except Exception as exc:
                logger.error("WalletEnricher worker loop encountered error: %s", exc)
                time.sleep(5.0)

    def _enrich_address(self, entity_id: int, address: str, etype: str, is_sanctioned: int):
        """Fetch blockchain details from public APIs."""
        logger.info("Enriching %s address: %s", etype, address)
        data = {
            "balance": 0.0,
            "tx_count": 0,
            "total_volume": 0.0,
            "first_active": None,
            "last_active": None,
            "is_sanctioned": is_sanctioned,
            "enrichment_source": "Unknown"
        }

        # Setup standard user agent header to prevent HTTP 403 errors
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TeleWire/1.0"}

        try:
            if etype == "crypto_btc":
                url = f"https://api.blockchair.com/bitcoin/dashboards/address/{address}"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                
                addr_data = res.get("data", {}).get(address, {}).get("address", {})
                if addr_data:
                    data["balance"] = float(addr_data.get("balance", 0)) / 1e8
                    data["tx_count"] = int(addr_data.get("n_tx", 0))
                    data["total_volume"] = float(addr_data.get("received_tot", 0)) / 1e8
                    data["first_active"] = addr_data.get("first_seen_receiving")
                    data["last_active"] = addr_data.get("last_seen_spending") or addr_data.get("last_seen_receiving")
                    data["enrichment_source"] = "Blockchair"

            elif etype == "crypto_eth":
                url = f"https://api.blockchair.com/ethereum/dashboards/address/{address}"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                
                addr_data = res.get("data", {}).get(address.lower(), {}).get("address", {})
                if addr_data:
                    data["balance"] = float(addr_data.get("balance", 0)) / 1e18
                    data["tx_count"] = int(addr_data.get("n_tx", 0))
                    data["total_volume"] = float(addr_data.get("received_tot", 0)) / 1e18
                    data["first_active"] = addr_data.get("first_seen_receiving")
                    data["last_active"] = addr_data.get("last_seen_spending") or addr_data.get("last_seen_receiving")
                    data["enrichment_source"] = "Blockchair"

            elif etype == "crypto_tron":
                url = f"https://api.trongrid.io/v1/accounts/{address}"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                
                tr_data = res.get("data", [])
                if tr_data:
                    account_data = tr_data[0]
                    data["balance"] = float(account_data.get("balance", 0)) / 1e6
                    # TronGrid does not expose transaction counts directly in account, but it does show TRC20 token list
                    # We can fetch asset counts or leave transaction counts.
                    data["enrichment_source"] = "TronGrid"

            elif etype == "crypto_ton":
                url = f"https://toncenter.com/api/v2/getAddressInformation?address={address}"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                
                result = res.get("result", {})
                if result:
                    data["balance"] = float(result.get("balance", 0)) / 1e9
                    # last_transaction_id.lt is not tx_count, but gives an idea of activity
                    lt = int(result.get("last_transaction_id", {}).get("lt", 0))
                    data["tx_count"] = 1 if lt > 0 else 0
                    data["enrichment_source"] = "TonCenter"

            # Persist to database
            self.db.upsert_wallet_enrichment(entity_id, data)
            logger.info("Enriched address %s successfully (Balance=%f)", address, data["balance"])

        except Exception as exc:
            logger.warning("Enrichment failed for address %s: %s", address, exc)
            # Still upsert what we have (e.g. sanctioned status)
            self.db.upsert_wallet_enrichment(entity_id, data)

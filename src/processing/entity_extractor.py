import re
import os
import urllib.request
import logging
import base64
import hashlib
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Checksum Validation Helpers
# ---------------------------------------------------------------------------

def decode_base58(s: str) -> bytes | None:
    """Decode a Base58 string into bytes."""
    ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    base = len(ALPHABET)
    num = 0
    try:
        for char in s:
            num = num * base + ALPHABET.index(char)
    except ValueError:
        return None
    
    combined = []
    while num > 0:
        num, remainder = divmod(num, 256)
        combined.append(remainder)
    
    # Preserve leading zeros
    for char in s:
        if char == '1':
            combined.append(0)
        else:
            break
            
    return bytes(reversed(combined))


def verify_btc_base58(address: str) -> bool:
    """Validate BTC Legacy/P2SH or TRON Base58Check address checksum."""
    decoded = decode_base58(address)
    if not decoded or len(decoded) < 5:
        return False
    data = decoded[:-4]
    checksum = decoded[-4:]
    h = hashlib.sha256(data).digest()
    double_h = hashlib.sha256(h).digest()
    return double_h[:4] == checksum


def verify_btc_bech32(address: str) -> bool:
    """Validate BTC Bech32/Bech32m (segwit/taproot) address."""
    addr = address.lower()
    pos = addr.rfind('1')
    if pos < 1 or pos + 7 > len(addr) or len(addr) > 90:
        return False
    hrp = addr[:pos]
    if hrp != "bc":
        return False
    
    ALPHABET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    data = []
    try:
        for c in addr[pos + 1:]:
            data.append(ALPHABET.index(c))
    except ValueError:
        return False
        
    # Bech32 polymod checksum verification
    generator = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    hrp_expand = [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]
    combined = hrp_expand + data
    
    chk = 1
    for value in combined:
        top = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
            
    # Valid specs: 1 (Bech32) or 0x2bc830a3 (Bech32m constant)
    return chk in (1, 0x2bc830a3)


def verify_eth_checksum(address: str) -> bool:
    """Basic validation for Ethereum hexadecimal addresses."""
    # ETH address pattern is already verified by regex; EIP-55 checksum is optional.
    # We enforce length and correct structure.
    return len(address) == 42 and address.startswith("0x")


def verify_ton_address(address: str) -> bool:
    """Validate TON user-friendly address (base64url + CRC16 checksum)."""
    # Clean URL-safe characters
    address_clean = address.replace('-', '+').replace('_', '/')
    # Pad base64
    address_clean += "=" * ((4 - len(address_clean) % 4) % 4)
    try:
        decoded = base64.b64decode(address_clean)
    except Exception:
        return False
        
    if len(decoded) != 36:
        return False
        
    data = decoded[:-2]
    checksum = decoded[-2:]
    
    # Calculate CRC-16 CCITT XMODEM
    crc = 0
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
            
    expected = crc.to_bytes(2, byteorder='big')
    return expected == checksum


# ---------------------------------------------------------------------------
# OFAC Sanctions Manager
# ---------------------------------------------------------------------------

class OFACSanctionChecker:
    def __init__(self, cache_dir: str = "data/sanction_lists"):
        self.cache_dir = cache_dir
        self.sanctioned_addresses = set()
        os.makedirs(cache_dir, exist_ok=True)
        self.load_local_lists()
        # Trigger async download
        import threading
        threading.Thread(target=self.download_ofac_lists, daemon=True).start()

    def load_local_lists(self):
        """Load lists already stored on disk."""
        addresses = set()
        for filename in ["sanctioned_addresses_XBT.txt", "sanctioned_addresses_ETH.txt", "sanctioned_addresses_TRX.txt"]:
            path = os.path.join(self.cache_dir, filename)
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        for line in fh:
                            addr = line.strip()
                            if addr and not addr.startswith("#"):
                                addresses.add(addr.lower())
                except Exception as exc:
                    logger.warning("Error reading sanction list %s: %s", filename, exc)
        self.sanctioned_addresses = addresses
        logger.info("Loaded %d OFAC sanctioned crypto addresses from cache", len(self.sanctioned_addresses))

    def download_ofac_lists(self):
        """Download latest lists from github community repository."""
        base_url = "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/"
        files = {
            "sanctioned_addresses_XBT.txt": "sanctioned_addresses_XBT.txt",
            "sanctioned_addresses_ETH.txt": "sanctioned_addresses_ETH.txt",
            "sanctioned_addresses_TRX.txt": "sanctioned_addresses_TRX.txt"
        }
        updated = False
        for remote_file, local_file in files.items():
            url = base_url + remote_file
            dest = os.path.join(self.cache_dir, local_file)
            try:
                # 5-second timeout for quick checks
                with urllib.request.urlopen(url, timeout=5) as response:
                    content = response.read().decode("utf-8")
                with open(dest, "w", encoding="utf-8") as fh:
                    fh.write(content)
                updated = True
                logger.info("Successfully updated OFAC list: %s", local_file)
            except Exception as exc:
                logger.warning("Failed to download OFAC list %s: %s", remote_file, exc)
        
        if updated:
            self.load_local_lists()

    def is_sanctioned(self, address: str) -> bool:
        """Check if an address is sanctioned."""
        return address.strip().lower() in self.sanctioned_addresses


# ---------------------------------------------------------------------------
# Main Entity Extractor
# ---------------------------------------------------------------------------

class EntityExtractor:
    def __init__(self, cache_dir: str = "data/sanction_lists"):
        self.sanction_checker = OFACSanctionChecker(cache_dir)
        
        # Regex definitions
        self.patterns = {
            "crypto_eth": re.compile(r"\b0x[a-fA-F0-9]{40}\b"),
            "crypto_btc_legacy": re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b"),
            "crypto_btc_bech32": re.compile(r"\bbc1[ac-hj-np-z0-9]{11,71}\b"),
            "crypto_tron": re.compile(r"\bT[a-km-zA-HJ-NP-Z1-9]{33}\b"),
            "crypto_ton": re.compile(r"\b[EeKkUu][Qq][a-zA-Z0-9_-]{46}\b"),
            "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
            "upi_id": re.compile(r"\b[a-zA-Z0-9.\-_]{2,64}@[a-zA-Z0-9\-]{2,32}\b"),
            "telegram_handle": re.compile(r"\B@[a-zA-Z0-9_]{5,32}\b"),
            "url": re.compile(r"\bhttps?://[a-zA-Z0-9\-\.\/\?\&\=\#\_\%\~\+]+"),
            "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
            # India phone number regex
            "phone_number": re.compile(r"\b(?:\+91[\-\s]?)?[6-9]\d{9}\b")
        }

    def extract(self, text: str) -> list:
        """
        Extract all valid entities from text.
        Returns a list of dicts: {'type': str, 'value': str, 'position': int, 'is_sanctioned': int}
        """
        if not text:
            return []
            
        results = []
        
        # We loop over each pattern and extract candidates
        for label, pattern in self.patterns.items():
            for match in pattern.finditer(text):
                value = match.group(0)
                start_pos = match.start()
                
                # Exclude overlaps or false positives
                # 1. UPI ID vs Email: If we matched a UPI ID, but it has a dot TLD suffix, it is an email
                if label == "upi_id":
                    if "." in value.split("@")[1]:
                        continue # Skip, it's an email
                
                # Checksums for crypto
                is_valid = True
                final_label = label
                
                if label == "crypto_btc_legacy":
                    is_valid = verify_btc_base58(value)
                    final_label = "crypto_btc"
                elif label == "crypto_btc_bech32":
                    is_valid = verify_btc_bech32(value)
                    final_label = "crypto_btc"
                elif label == "crypto_eth":
                    is_valid = verify_eth_checksum(value)
                elif label == "crypto_tron":
                    is_valid = verify_btc_base58(value) # Tron uses the same base58check algorithm
                elif label == "crypto_ton":
                    is_valid = verify_ton_address(value)
                    
                if not is_valid:
                    continue
                    
                is_sanctioned = 0
                if final_label in ("crypto_btc", "crypto_eth", "crypto_tron"):
                    is_sanctioned = 1 if self.sanction_checker.is_sanctioned(value) else 0
                    
                results.append({
                    "type": final_label,
                    "value": value,
                    "position": start_pos,
                    "is_sanctioned": is_sanctioned
                })
                
        return results

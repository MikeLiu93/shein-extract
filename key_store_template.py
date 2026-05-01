"""
TEMPLATE — do not edit directly. The build script `make_key_store.py` reads
the raw API key from `.build_key.txt` (gitignored, owner-only) and produces
`key_store.py` (also gitignored) with the encoded key.

key_store.py is bundled into the .exe by PyInstaller so employees never see
the plaintext. Determined attackers can extract it by reverse-engineering
the .exe — that's accepted (Mike's Q1 decision: light obfuscation, set
monthly cap on Anthropic dashboard as the real defense).
"""

# Will be replaced by make_key_store.py with the actual encoded value.
ENCODED_KEY = ""
PASSPHRASE = "shein-extract-2026"


def get_obfuscated_key() -> str:
    """Decode the bundled obfuscated key. Returns '' if not set."""
    if not ENCODED_KEY:
        return ""
    import base64
    try:
        raw = base64.b64decode(ENCODED_KEY)
        out = bytearray()
        for i, b in enumerate(raw):
            out.append(b ^ ord(PASSPHRASE[i % len(PASSPHRASE)]))
        return out.decode("utf-8")
    except Exception:
        return ""

import os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
import hashlib

KEY_PATH = Path(os.getcwd()) / ".agentwitness" / "keys"

class CryptoSigner:
    def __init__(self, key_dir: Path = KEY_PATH):
        self.key_dir = key_dir
        self.private_key_path = self.key_dir / "private.pem"
        self.public_key_path = self.key_dir / "public.pem"
        self._ensure_keys()

    def _ensure_keys(self):
        if not self.key_dir.exists():
            self.key_dir.mkdir(parents=True, exist_ok=True)
            
        if not self.private_key_path.exists():
            private_key = ed25519.Ed25519PrivateKey.generate()
            public_key = private_key.public_key()
            
            with open(self.private_key_path, "wb") as f:
                f.write(private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                ))
                
            with open(self.public_key_path, "wb") as f:
                f.write(public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                ))

    def _get_private_key(self):
        with open(self.private_key_path, "rb") as f:
            return serialization.load_pem_private_key(
                f.read(),
                password=None
            )

    def _get_public_key(self):
        with open(self.public_key_path, "rb") as f:
            return serialization.load_pem_public_key(f.read())

    def sign(self, payload: str) -> str:
        private_key = self._get_private_key()
        signature = private_key.sign(payload.encode("utf-8"))
        return signature.hex()

    def verify(self, payload: str, signature_hex: str) -> bool:
        public_key = self._get_public_key()
        try:
            public_key.verify(bytes.fromhex(signature_hex), payload.encode("utf-8"))
            return True
        except Exception:
            return False

def hash_payload(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

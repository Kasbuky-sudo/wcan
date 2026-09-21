import hashlib
import hmac
import os
from base64 import b64encode, b64decode

class FileCrypto:
    def __init__(self, password: str):
        self.key = hashlib.sha256(password.encode()).digest() if password else None

    def encrypt(self, data: bytes) -> bytes:
        if self.key is None:
            return data
        h = hmac.new(self.key, data, hashlib.sha256)
        return h.digest() + data

    def decrypt(self, encrypted_data: bytes) -> bytes:
        if self.key is None:
            return encrypted_data
        if len(encrypted_data) < 32:
            raise ValueError("Invalid encrypted data")
        mac = encrypted_data[:32]
        data = encrypted_data[32:]
        h = hmac.new(self.key, data, hashlib.sha256)
        if not hmac.compare_digest(mac, h.digest()):
            raise ValueError("MAC verification failed")
        return data

    def encrypt_to_file(self, file_path: str, data: bytes):
        encrypted_data = self.encrypt(data)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'wb') as f:
            f.write(encrypted_data)

    def decrypt_from_file(self, file_path: str) -> bytes:
        with open(file_path, 'rb') as f:
            data = f.read()
        return self.decrypt(data)

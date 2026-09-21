from werss.file import FileCrypto
from werss.config import cfg
import json
import os


class KeyStore:
    key_file = "data/key.lic"

    def __init__(self):
        self.store = FileCrypto(cfg.get("safe.lic_key", "store.csol.store.werss"))

    def save(self, text):
        items = []
        if type(text) != str:
            for item in text:
                items.append(item)
        text = json.dumps(items)

        os.makedirs(os.path.dirname(self.key_file), exist_ok=True)
        self.store.encrypt_to_file(self.key_file, text.encode("utf-8"))

    def load(self):
        try:
            text = self.store.decrypt_from_file(self.key_file).decode("utf-8")
            items = json.loads(text)
            return self._filter_items(items)
        except Exception:
            return ""

    def _filter_items(self, items):
        new_items = []
        for item in items:
            if item.get('name') == "_clck":
                continue
            if item.get('name') == "token":
                continue
            new_items.append(item)
        return new_items


Store = KeyStore()

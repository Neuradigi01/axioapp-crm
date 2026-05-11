import base64
import hashlib
from cryptography.fernet import Fernet
from config import FERNET_KEY


class FernetUtil:
    def __init__(self, key: str):
        derived = hashlib.sha256(key.encode("utf-8")).digest()
        self.fernet = Fernet(base64.urlsafe_b64encode(derived))

    def encrypt(self, plain_text: str) -> str:
        return self.fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_text: str) -> str:
        return self.fernet.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")


fernet = FernetUtil(FERNET_KEY)

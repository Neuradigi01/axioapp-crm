from src.core.security.password import hash_password, verify_password


def test_hash_password_returns_hash():
    hashed = hash_password("testpassword")
    assert hashed != "testpassword"
    assert len(hashed) > 0


def test_verify_correct_password():
    hashed = hash_password("testpassword")
    assert verify_password("testpassword", hashed) is True


def test_verify_wrong_password():
    hashed = hash_password("testpassword")
    assert verify_password("wrongpassword", hashed) is False


def test_hash_is_unique():
    hash1 = hash_password("testpassword")
    hash2 = hash_password("testpassword")
    assert hash1 != hash2

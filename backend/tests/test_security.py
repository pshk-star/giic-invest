"""Pruebas de seguridad: hashing de contraseñas y tokens JWT HS256."""
import pytest

from app import security as sec


def test_password_hash_verify_roundtrip():
    h = sec.hash_password("Correct-Horse-9!")
    assert sec.verify_password("Correct-Horse-9!", h)
    assert not sec.verify_password("wrong", h)


def test_password_hash_is_salted():
    assert sec.hash_password("same-pass-123A!") != sec.hash_password("same-pass-123A!")


def test_verify_rejects_garbage_stored():
    assert not sec.verify_password("x", "no-es-un-hash-valido")


def test_password_strength_rules():
    ok, problems = sec.validate_password_strength("Str0ng-Passw0rd!")
    assert ok and problems == []
    ok2, problems2 = sec.validate_password_strength("weak")
    assert not ok2 and len(problems2) >= 3


def test_jwt_roundtrip():
    tok = sec.create_access_token("pablo", "secret-key", expires_seconds=60, now=1000)
    payload = sec.decode_token(tok, "secret-key", now=1000)
    assert payload["sub"] == "pablo"
    assert payload["exp"] == 1060


def test_jwt_tampered_signature_rejected():
    tok = sec.create_access_token("pablo", "secret-key", now=1000)
    tampered = tok[:-4] + ("AAAA" if not tok.endswith("AAAA") else "BBBB")
    with pytest.raises(ValueError):
        sec.decode_token(tampered, "secret-key", now=1000)


def test_jwt_wrong_secret_rejected():
    tok = sec.create_access_token("pablo", "secret-key", now=1000)
    with pytest.raises(ValueError):
        sec.decode_token(tok, "otro-secreto", now=1000)


def test_jwt_expired_rejected():
    tok = sec.create_access_token("pablo", "secret-key", expires_seconds=30, now=1000)
    with pytest.raises(ValueError):
        sec.decode_token(tok, "secret-key", now=1031)


def test_create_token_requires_secret():
    with pytest.raises(ValueError):
        sec.create_access_token("pablo", "")

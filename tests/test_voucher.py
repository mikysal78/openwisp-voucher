from datetime import date

import pytest

from openwisp_voucher.voucher import (
    PASSWORD_ALPHABET,
    Voucher,
    batch_name,
    days_for_expiration,
    expiration_for_days,
    generate_password,
    share_text,
    valid_prefix,
    valid_username,
    wifi_qr_payload,
)


def test_expiration_counts_today():
    today = date(2026, 10, 26)
    assert expiration_for_days(1, today) == today
    assert expiration_for_days(3, today) == date(2026, 10, 28)
    assert days_for_expiration(date(2026, 10, 28), today) == 3
    with pytest.raises(ValueError):
        expiration_for_days(0, today)


def test_password_has_no_ambiguous_characters():
    for _ in range(50):
        password = generate_password(10)
        assert len(password) == 10
        assert set(password) <= set(PASSWORD_ALPHABET)
        assert not set(password) & set("0O1lI")


def test_usernames_and_prefixes():
    assert valid_username("pippo")
    assert valid_username("mario.rossi@hotel")
    assert not valid_username("mario rossi")
    assert not valid_username("")
    assert valid_prefix("ospite")
    assert not valid_prefix("ospite camera")
    assert not valid_prefix("x" * 21)


def test_batch_names_are_unique():
    assert len({batch_name("serie") for _ in range(20)}) == 20


def test_wifi_qr_escapes_special_characters():
    assert wifi_qr_payload("NINUX") == "WIFI:T:nopass;S:NINUX;;"
    assert wifi_qr_payload('a;b,c:"d', "p;w") == r'WIFI:T:WPA;S:a\;b\,c\:\"d;P:p\;w;;'


def test_share_text():
    text = share_text(Voucher("pippo", "abc23456", date(2026, 10, 28)), "NINUX", "www.example.org")
    assert "pippo" in text and "abc23456" in text and "28/10/2026" in text
    assert text.splitlines()[0].endswith("NINUX")

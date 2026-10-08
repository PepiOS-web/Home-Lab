import pytest

from app.control_auth import ControlAuthError, authorize_control


def test_control_auth_accepts_token_only_from_portal_origin():
    authorize_control("https://portal.home.arpa", "Bearer " + "a" * 64, "a" * 64)


@pytest.mark.parametrize(
    ("origin", "authorization", "expected_status"),
    [
        ("https://attacker.example", "Bearer " + "a" * 64, 403),
        ("https://portal.home.arpa", "Bearer " + "b" * 64, 401),
        ("https://portal.home.arpa", "", 401),
    ],
)
def test_control_auth_rejects_bad_origin_or_token(origin, authorization, expected_status):
    with pytest.raises(ControlAuthError) as error:
        authorize_control(origin, authorization, "a" * 64)
    assert error.value.status_code == expected_status


def test_control_auth_is_disabled_without_secret():
    with pytest.raises(ControlAuthError) as error:
        authorize_control("https://portal.home.arpa", "Bearer anything", "")
    assert error.value.status_code == 503

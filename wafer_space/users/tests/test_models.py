from wafer_space.users.models import User


def test_user_get_absolute_url(user: User):
    assert user.get_absolute_url() == f"/users/{user.username}/"


def test_get_full_name_is_name(user: User):
    user.name = "Ada Lovelace"
    assert user.get_full_name() == "Ada Lovelace"


def test_get_full_name_empty_when_no_name(user: User):
    """Never "None None": first_name/last_name are removed (issue #304)."""
    user.name = ""
    assert user.get_full_name() == ""


def test_get_short_name_is_name(user: User):
    user.name = "Ada Lovelace"
    assert user.get_short_name() == "Ada Lovelace"

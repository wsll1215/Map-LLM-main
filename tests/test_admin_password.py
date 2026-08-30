import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "xy_neo4j.settings")

import django

django.setup()

from django.contrib import admin
from django.test import RequestFactory

from accounts.admin import UserProfileAdmin
from accounts.models import UserProfile


def _field_names(fieldsets):
    return {
        field
        for _section, options in fieldsets
        for field in options.get("fields", ())
    }


def test_user_admin_uses_hashed_password_field_and_hides_legacy_plaintext_field():
    admin_instance = UserProfileAdmin(UserProfile, admin.site)
    field_names = _field_names(admin_instance.fieldsets)

    assert "password" in field_names
    assert "mpassword" not in field_names

    request = RequestFactory().get("/admin/accounts/userprofile/1/change/")
    change_form_class = admin_instance.get_form(request, obj=UserProfile())
    assert "password" in change_form_class.base_fields
    assert "mpassword" not in change_form_class.base_fields

    add_form_class = admin_instance.get_form(request)
    assert {"password1", "password2"}.issubset(add_form_class.base_fields)
    assert "mpassword" not in add_form_class.base_fields

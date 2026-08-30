from django.conf.urls import url, include
from .views import *

urlpatterns = [
    url(r"^api/tokens/?$", issue_token, name="issue_token"),
    url(r"^api/tokens/refresh/?$", refresh_token, name="refresh_token"),
    url(r"^api/tokens/current/?$", revoke_current_token, name="revoke_current_token"),
    url(r"^api/me/?$", current_user, name="current_user"),
    url(r"^modify$", modify, name="modify"),
    url(r"^login/?$", user_login, name="login"),
    url(r"^logout$", user_logout, name="logout"),
    url(r"^register$", do_register, name="register"),
]

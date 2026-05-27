from django.urls import path
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView

from .views import (
    AdminUserDetailView,
    AdminUserListView,
    AdminUserRoleUpdateView,
    AdminUserStatusUpdateView,
    ChangePasswordView,
    LoginView,
    MeView,
    RegisterView,
    RequestPasswordResetView,
    ConfirmPasswordResetView,
)

app_name = "accounts"

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", TokenBlacklistView.as_view(), name="logout"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    path("me/", MeView.as_view(), name="me"),
    path("me/password/", ChangePasswordView.as_view(), name="change_password"),

    path('password-reset/', RequestPasswordResetView.as_view(), name='password_reset_request'),
    path('password-reset/confirm/', ConfirmPasswordResetView.as_view(), name='password_reset_confirm'),

    path("users/", AdminUserListView.as_view(), name="admin_users_list"),
    path("users/<int:pk>/", AdminUserDetailView.as_view(),
         name="admin_users_detail"),
    path("users/<int:pk>/role/", AdminUserRoleUpdateView.as_view(),
         name="admin_users_role_update"),
    path("users/<int:pk>/status/", AdminUserStatusUpdateView.as_view(),
         name="admin_users_status_update"),
]

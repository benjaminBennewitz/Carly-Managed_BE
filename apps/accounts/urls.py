# apps/accounts/urls.py
"""Routet sämtliche Konto- und Sitzungsoperationen."""

from django.urls import path

from apps.accounts.views import (
    CsrfView,
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RegisterView,
    VerificationConfirmView,
    VerificationRequestView,
)

urlpatterns = [
    path("csrf/", CsrfView.as_view(), name="csrf"),
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path("password/change/", PasswordChangeView.as_view(), name="password-change"),
    path(
        "password/reset/request/", PasswordResetRequestView.as_view(), name="password-reset-request"
    ),
    path(
        "password/reset/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"
    ),
    path("email/verify/request/", VerificationRequestView.as_view(), name="email-verify-request"),
    path("email/verify/confirm/", VerificationConfirmView.as_view(), name="email-verify-confirm"),
]

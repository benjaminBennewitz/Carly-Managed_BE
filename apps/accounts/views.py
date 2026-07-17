# apps/accounts/views.py
"""Stellt sichere, klar begrenzte Kontoendpunkte bereit."""

from django.contrib.auth import update_session_auth_hash
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import AccountTokenPurpose
from apps.accounts.serializers import (
    CurrentUserSerializer,
    EmailOnlySerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    RegistrationSerializer,
    TokenSerializer,
)
from apps.accounts.services import (
    authenticate_user,
    consume_account_token,
    end_session,
    register_user,
    request_password_reset,
    send_verification_email,
)
from apps.common.throttles import (
    LoginRateThrottle,
    RecoveryRateThrottle,
    RegistrationRateThrottle,
    VerificationRateThrottle,
)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """Setzt das CSRF-Cookie vor der ersten schreibenden SPA-Anfrage."""

    authentication_classes: list[type] = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        """Liefert den Token zusätzlich für leichtes lokales Debugging."""
        return Response({"csrfToken": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
class RegisterView(APIView):
    """Registriert ein Konto und startet eine Browser-Sitzung."""

    authentication_classes: list[type] = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RegistrationRateThrottle]

    @extend_schema(request=RegistrationSerializer, responses={201: CurrentUserSerializer})
    def post(self, request: Request) -> Response:
        """Validiert und persistiert eine Registrierung atomar."""
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = register_user(
            request=request,
            display_name=serializer.validated_data["displayName"],
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        send_verification_email(user=user, request=request)
        return Response(
            {"user": CurrentUserSerializer(user, context={"request": request}).data},
            status=status.HTTP_201_CREATED,
        )


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    """Authentifiziert ein Konto über eine rotierte Django-Sitzung."""

    authentication_classes: list[type] = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginRateThrottle]

    @extend_schema(request=LoginSerializer, responses={200: CurrentUserSerializer})
    def post(self, request: Request) -> Response:
        """Startet bei gültigen Zugangsdaten eine Sitzung."""
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate_user(
            request=request,
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
            remember_me=serializer.validated_data["rememberMe"],
        )
        return Response({"user": CurrentUserSerializer(user, context={"request": request}).data})


class LogoutView(APIView):
    """Beendet die aktuelle Sitzung serverseitig."""

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        """Löscht Sitzung und Authentifizierungsdaten."""
        end_session(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """Liest und ändert das aktuell angemeldete Konto."""

    @extend_schema(responses={200: CurrentUserSerializer})
    def get(self, request: Request) -> Response:
        """Liefert den aktuellen Nutzer zur Sitzungswiederherstellung."""
        return Response(
            {"user": CurrentUserSerializer(request.user, context={"request": request}).data}
        )

    @extend_schema(request=CurrentUserSerializer, responses={200: CurrentUserSerializer})
    def patch(self, request: Request) -> Response:
        """Aktualisiert ausschließlich freigegebene Profildaten."""
        serializer = CurrentUserSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"user": serializer.data})


class PasswordChangeView(APIView):
    """Ändert ein Passwort nach erneuter Kenntnisprüfung."""

    @extend_schema(request=PasswordChangeSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        """Setzt ein neues Passwort und erhält nur die aktuelle Sitzung."""
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data["currentPassword"]):
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"currentPassword": ["Das aktuelle Passwort ist nicht korrekt."]},
                code="invalid_current_password",
            )
        request.user.set_password(serializer.validated_data["newPassword"])
        request.user.save(update_fields=("password",))
        update_session_auth_hash(request, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class VerificationRequestView(APIView):
    """Fordert eine neue Bestätigungsnachricht an."""

    throttle_classes = [VerificationRateThrottle]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        """Versendet nur bei noch nicht bestätigter Adresse eine Nachricht."""
        if not request.user.email_verified:
            send_verification_email(user=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="dispatch")
class VerificationConfirmView(APIView):
    """Bestätigt eine E-Mail-Adresse über ein Einmal-Token."""

    authentication_classes: list[type] = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RecoveryRateThrottle]

    @extend_schema(request=TokenSerializer, responses={200: CurrentUserSerializer})
    def post(self, request: Request) -> Response:
        """Markiert die Adresse nach erfolgreichem Tokenverbrauch als bestätigt."""
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = consume_account_token(
            raw_token=serializer.validated_data["token"],
            purpose=AccountTokenPurpose.VERIFY_EMAIL,
        )
        user = token.user
        if not user.email_verified_at:
            user.email_verified_at = timezone.now()
            user.save(update_fields=("email_verified_at",))
        return Response({"user": CurrentUserSerializer(user, context={"request": request}).data})


@method_decorator(csrf_protect, name="dispatch")
class PasswordResetRequestView(APIView):
    """Startet einen enumerationssicheren Passwort-Reset."""

    authentication_classes: list[type] = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RecoveryRateThrottle]

    @extend_schema(request=EmailOnlySerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        """Antwortet unabhängig vom Kontobestand identisch."""
        serializer = EmailOnlySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_password_reset(email=serializer.validated_data["email"], request=request)
        return Response(
            {"message": "Falls ein aktives Konto existiert, wurde eine Nachricht versendet."}
        )


@method_decorator(csrf_protect, name="dispatch")
class PasswordResetConfirmView(APIView):
    """Setzt das Passwort mit einem kurzlebigen Einmal-Token zurück."""

    authentication_classes: list[type] = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RecoveryRateThrottle]

    @extend_schema(request=PasswordResetConfirmSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        """Ändert das Passwort und hebt bestehende Sperren auf."""
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = consume_account_token(
            raw_token=serializer.validated_data["token"],
            purpose=AccountTokenPurpose.RESET_PASSWORD,
        )
        user = token.user
        user.set_password(serializer.validated_data["newPassword"])
        user.failed_login_count = 0
        user.locked_until = None
        user.save(update_fields=("password", "failed_login_count", "locked_until"))
        return Response(status=status.HTTP_204_NO_CONTENT)

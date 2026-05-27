from django.contrib.auth import get_user_model
from rest_framework import filters, generics, permissions
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Profile
from .permissions import IsAdminUser
from .throttles import LoginThrottle, RegisterThrottle
from .serializers import (
    AdminUserDetailSerializer,
    AdminUserListSerializer,
    ChangePasswordSerializer,
    UserRegistrationSerializer,
    UserRoleUpdateSerializer,
    UserSerializer,
    UserStatusUpdateSerializer,
)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RegisterThrottle]


class LoginView(TokenObtainPairView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginThrottle]


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class ChangePasswordView(generics.GenericAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        serializer = self.get_serializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        refresh_token = request.data.get("refresh_token")
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except TokenError:
                pass

        new_refresh = RefreshToken.for_user(request.user)
        return Response(
            {
                "detail": "Contraseña actualizada correctamente.",
                "access": str(new_refresh.access_token),
                "refresh": str(new_refresh),
            }
        )


class AdminUserListView(generics.ListAPIView):
    serializer_class = AdminUserListSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "username",
        "email",
        "first_name",
        "last_name",
    ]
    ordering_fields = [
        "id",
        "username",
        "email",
        "is_active",
        "date_joined",
    ]
    ordering = ["id"]

    def get_queryset(self):
        queryset = User.objects.select_related("profile").all()

        role = self.request.query_params.get("role")
        is_active = self.request.query_params.get("is_active")

        if role in Profile.Role.values:
            queryset = queryset.filter(profile__role=role)

        if is_active in ["true", "false"]:
            queryset = queryset.filter(is_active=is_active == "true")

        return queryset


class AdminUserDetailView(generics.RetrieveUpdateAPIView):
    queryset = User.objects.select_related("profile")
    serializer_class = AdminUserDetailSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]
    http_method_names = ["get", "patch"]


class AdminUserRoleUpdateView(generics.UpdateAPIView):
    queryset = User.objects.select_related("profile")
    serializer_class = UserRoleUpdateSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]
    http_method_names = ["patch"]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["user_instance"] = self.get_object()
        return context


class AdminUserStatusUpdateView(generics.UpdateAPIView):
    queryset = User.objects.select_related("profile")
    serializer_class = UserStatusUpdateSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]
    http_method_names = ["patch"]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["user_instance"] = self.get_object()
        return context

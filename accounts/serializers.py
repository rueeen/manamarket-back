from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Profile
from .permissions import get_user_role

User = get_user_model()


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "password",
            "first_name",
            "last_name",
        )
        read_only_fields = ("id",)

    def validate_email(self, value):
        if value and User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "Ya existe un usuario con este correo.")
        return value

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError(
                "Ya existe un usuario con este nombre de usuario.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")

        user = User(**validated_data)
        user.set_password(password)
        user.save()

        Profile.objects.get_or_create(
            user=user,
            defaults={"role": Profile.Role.CUSTOMER},
        )

        return user


class UserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "role",
        )
        read_only_fields = fields

    def get_role(self, obj):
        return get_user_role(obj)


class AdminUserListSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "is_active",
            "is_staff",
            "is_superuser",
        )

    def get_role(self, obj):
        return get_user_role(obj)

    def get_full_name(self, obj):
        return obj.get_full_name()


class AdminUserDetailSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(
        choices=Profile.Role.choices,
        required=False,
    )

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "is_staff",
            "role",
        )
        read_only_fields = ("id",)

    def validate(self, attrs):
        request = self.context.get("request")
        instance = self.instance

        if not request or not instance:
            return attrs

        is_self = request.user == instance

        if is_self and attrs.get("is_active") is False:
            raise serializers.ValidationError({
                "is_active": "No puedes desactivar tu propia cuenta."
            })

        if is_self and attrs.get("role") and attrs["role"] != Profile.Role.ADMIN:
            raise serializers.ValidationError({
                "role": "No puedes quitarte a ti mismo el rol de administrador."
            })

        return attrs

    def update(self, instance, validated_data):
        role = validated_data.pop("role", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        if role is not None:
            profile, _ = Profile.objects.get_or_create(user=instance)
            profile.role = role
            profile.save(update_fields=["role", "updated_at"])

        return instance


class UserRoleUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Profile.Role.choices)

    def validate_role(self, value):
        request = self.context.get("request")
        instance = self.context.get("user_instance")

        if request and instance and request.user == instance and value != Profile.Role.ADMIN:
            raise serializers.ValidationError(
                "No puedes quitarte a ti mismo el rol de administrador."
            )

        return value

    def update(self, instance, validated_data):
        profile, _ = Profile.objects.get_or_create(user=instance)
        profile.role = validated_data["role"]
        profile.save(update_fields=["role", "updated_at"])
        return instance


class UserStatusUpdateSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()

    def validate_is_active(self, value):
        request = self.context.get("request")
        instance = self.context.get("user_instance")

        if request and instance and request.user == instance and value is False:
            raise serializers.ValidationError(
                "No puedes desactivar tu propia cuenta."
            )

        return value

    def update(self, instance, validated_data):
        instance.is_active = validated_data["is_active"]
        instance.save(update_fields=["is_active"])
        return instance


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
    )

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError(
                "La contraseña actual es incorrecta."
            )
        return value

    def validate_new_password(self, value):
        current = self.initial_data.get("current_password", "")
        if value == current:
            raise serializers.ValidationError(
                "La nueva contraseña debe ser diferente a la actual."
            )
        return value

    def save(self):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user

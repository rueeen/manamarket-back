from rest_framework.permissions import BasePermission

from .models import Profile


def get_user_role(user):
    """
    Devuelve el rol real del usuario dentro del sistema.

    Regla:
    - superuser siempre es admin.
    - staff puede ser admin si así lo define su Profile.
    - usuario sin profile se trata como customer.
    """
    if not user or not user.is_authenticated:
        return None

    if user.is_superuser:
        return Profile.Role.ADMIN

    profile = getattr(user, "profile", None)

    if not profile:
        return Profile.Role.CUSTOMER

    return profile.role


def has_role(user, *roles):
    return get_user_role(user) in roles


def is_admin_user(user):
    return has_role(user, Profile.Role.ADMIN)


def is_worker_user(user):
    return has_role(user, Profile.Role.WORKER)


def is_customer_user(user):
    return has_role(user, Profile.Role.CUSTOMER)


class IsAdminUser(BasePermission):
    message = "Solo los administradores pueden realizar esta acción."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and is_admin_user(request.user)
        )


class IsAdminOrWorkerUser(BasePermission):
    message = "Solo administradores o trabajadores pueden realizar esta acción."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and has_role(
                request.user,
                Profile.Role.ADMIN,
                Profile.Role.WORKER,
            )
        )

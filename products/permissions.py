from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.permissions import is_admin_user, is_worker_user


class IsAdminOrWorkerOrReadOnly(BasePermission):
    """
    Permite lectura pública y escritura solo a admin o worker.
    """

    message = "Solo administradores o trabajadores pueden modificar este recurso."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        user = request.user

        return bool(
            user
            and user.is_authenticated
            and (
                is_admin_user(user)
                or is_worker_user(user)
            )
        )

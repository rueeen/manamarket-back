from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile

User = get_user_model()


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Crea automáticamente el profile del usuario.

    Reglas:
    - Si es superuser, nace como admin.
    - Si es usuario normal, nace como customer.
    - No se pisa el rol manualmente en cada guardado.
    """
    if not created:
        return

    default_role = (
        Profile.Role.ADMIN
        if instance.is_superuser
        else Profile.Role.CUSTOMER
    )

    Profile.objects.get_or_create(
        user=instance,
        defaults={"role": default_role},
    )

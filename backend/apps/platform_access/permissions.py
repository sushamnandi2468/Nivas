from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import BasePermission

from apps.platform_access.models import PlatformRoleGrant


class IsPlatformAdmin(BasePermission):
    message = "An active platform administrator grant is required."

    def has_permission(self, request, view):
        instant = timezone.now()
        return (
            request.user.is_authenticated
            and PlatformRoleGrant.objects.filter(
                user=request.user,
                role=PlatformRoleGrant.Role.PLATFORM_ADMIN,
                status=PlatformRoleGrant.Status.ACTIVE,
                starts_at__lte=instant,
            )
            .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=instant))
            .exists()
        )
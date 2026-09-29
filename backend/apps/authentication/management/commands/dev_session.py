import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.authentication.tokens import SessionAccessToken
from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import Society, StaffMembership


class Command(BaseCommand):
    help = "Create a guarded development identity and emit a real short-lived access token."

    def add_arguments(self, parser):
        parser.add_argument("--phone", default="+919876543210")
        parser.add_argument("--society-code", default="NIVASOPS-DEV")
        parser.add_argument(
            "--role",
            choices=[choice.value for choice in StaffMembership.Role],
            default=StaffMembership.Role.FACILITY_MANAGER,
        )

    def handle(self, *args, **options):
        if not settings.DEBUG or not settings.ALLOW_DEV_SESSION_BOOTSTRAP:
            raise CommandError(
                "Development sessions require DEBUG=true and "
                "ALLOW_DEV_SESSION_BOOTSTRAP=true."
            )

        society_code = options["society_code"].strip().upper()
        society, _ = Society.objects.get_or_create(registration_code=society_code)
        user = User.objects.filter(phone=options["phone"]).first()
        if user is None:
            user = User.objects.create_user(phone=options["phone"])

        with transaction.atomic():
            set_local_society_id(society.id)
            membership = StaffMembership.objects.filter(
                society=society,
                user=user,
                is_active=True,
            ).first()
            if membership is None:
                membership = StaffMembership.objects.create(
                    society=society,
                    user=user,
                    role=options["role"],
                )
            elif membership.role != options["role"]:
                membership.role = options["role"]
                membership.save(update_fields=("role", "updated_at"))

        access_token = SessionAccessToken.for_user(user)
        self.stdout.write(
            json.dumps(
                {
                    "access_token": str(access_token),
                    "expires_in": int(access_token["exp"] - access_token["iat"]),
                    "society_id": str(society.id),
                    "user_id": str(user.id),
                    "membership_id": str(membership.id),
                    "role": membership.role,
                }
            )
        )
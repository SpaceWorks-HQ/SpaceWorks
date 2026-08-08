"""Drop the last ``User.role="guest_admin"`` values ahead of the enum removal.

The global ``User.role`` has not decided authority since the RBAC layer moved to
per-makerspace memberships -- ``rbac`` keys everything on the membership, and
``services_staff._global_role_for_membership`` has already stopped assigning this value.
The one place it was still read is ``permissions.STAFF_ROLES``, and that is reached only by
``IsStaff``, whose sole ``StaffAPIView`` subclass (``EvidenceUploadUrlView``) overrides
``permission_classes`` -- so no request path resolves through it today.

That is what makes ``requester`` the correct landing value rather than ``space_manager``:
the column is a label, the membership is the authority, and picking the staff-flavoured
value would grant real access on the day something starts reading this column again.
Anyone who actually does front-desk work holds the makerspace membership that says so.

Reverse is a no-op by design. Nothing records which ``requester`` rows used to hold the
retired label, and guessing would hand a staff-flavoured global role to ordinary members.
The forward direction removes no authority, so the reverse has none to restore.
"""

from django.db import migrations

GUEST_ADMIN = "guest_admin"
REQUESTER = "requester"


def forwards(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role=GUEST_ADMIN).update(role=REQUESTER)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_platformsocialauthsettings_socialidentity_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

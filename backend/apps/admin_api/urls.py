from .urls_api_clients import (
    client_urlpatterns,
    makerspace_urlpatterns as api_client_makerspace_urlpatterns,
)
from .urls_inventory import urlpatterns as inventory_urlpatterns
from .urls_machine_service import urlpatterns as machine_service_urlpatterns
from .urls_machines import urlpatterns as machine_urlpatterns
from .urls_makerspaces import urlpatterns as makerspace_urlpatterns
from .urls_memberships import management_urlpatterns, roster_urlpatterns
from .urls_notifications import urlpatterns as notification_urlpatterns
from .urls_platform import settings_urlpatterns, urlpatterns as platform_urlpatterns
from .urls_staff import urlpatterns as staff_urlpatterns
from .urls_utils import _separable as _separable


urlpatterns = [
    *platform_urlpatterns,
    *roster_urlpatterns,
    *machine_service_urlpatterns,
    *management_urlpatterns,
    *machine_urlpatterns,
    *settings_urlpatterns,
    *makerspace_urlpatterns,
    *inventory_urlpatterns,
    *api_client_makerspace_urlpatterns,
    *notification_urlpatterns,
    *client_urlpatterns,
    *staff_urlpatterns,
]

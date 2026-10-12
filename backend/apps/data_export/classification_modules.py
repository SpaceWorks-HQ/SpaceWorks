"""WP2 public-site choices travel with the existing makerspace configuration."""

from .classification_domain import EXPORTED_MODEL_FIELDS as DOMAIN_FIELDS

EXPORTED_MODEL_FIELDS = {
    "makerspaces.Makerspace": DOMAIN_FIELDS["makerspaces.Makerspace"]
    + " public_site_enabled public_landing_page",
}

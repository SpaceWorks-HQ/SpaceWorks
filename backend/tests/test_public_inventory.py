"""Public inventory regression collection; implementation split by test groups."""

from tests.public_inventory_helpers import (
    api_client,
    public_makerspace,
    public_inventory_url,
    public_inventory_code_url,
    public_inventory_categories_url,
    signed_headers,
    create_product,
    public_makerspaces_url,
    get_single_product,
    PUBLIC_PRODUCT_FIELDS,
    pytestmark,
)

from tests.public_inventory_cases_1 import (
    test_public_lookup_prefers_slug_over_colliding_public_code,
    test_lists_only_public_non_archived_products,
    test_public_inventory_searches_name_and_description,
    test_public_product_payload_includes_category_fields,
    test_public_inventory_filters_by_category_slug,
    test_public_inventory_sorts_by_most_used,
    test_public_inventory_sorts_by_popular,
    test_public_categories_endpoint_returns_non_empty_public_categories,
    test_product_clean_rejects_category_from_other_makerspace,
)

from tests.public_inventory_cases_2 import (
    test_lists_public_makerspaces,
    test_status_only_mode_hides_exact_count,
    test_exact_count_shows_count_when_enabled,
    test_exact_count_without_show_count_falls_back_to_status_only,
    test_hidden_mode_returns_null_availability,
    test_status_labels,
    test_never_exposes_internal_fields,
    test_unknown_slug_returns_404,
    test_public_inventory_accepts_public_code,
    test_public_disabled_returns_404,
    test_hmac_disabled_by_default,
    test_hmac_allows_signed_public_inventory_request,
)

from tests.public_inventory_cases_3 import (
    test_frontend_api_client_allows_matching_origin_and_makerspace_code,
    test_frontend_api_client_rejects_other_makerspace_code,
    test_hmac_rejects_unsigned_or_invalid_public_inventory_request,
    test_openapi_schema_includes_public_inventory_path,
    test_backend_docs_are_available_at_root_and_api_docs_alias,
)

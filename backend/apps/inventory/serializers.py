from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from apps.inventory import public_image_storage
from apps.inventory.public_availability import get_public_availability


AVAILABILITY_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["status_only", "exact_count"],
        },
        "label": {
            "type": "string",
            "enum": ["Available", "Limited", "Unavailable"],
        },
        "count": {"type": "integer", "minimum": 0},
    },
    "required": ["mode"],
}


class PublicProductSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    category_id = serializers.IntegerField(
        source="category.id",
        read_only=True,
        allow_null=True,
    )
    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
        allow_null=True,
    )
    category_slug = serializers.CharField(
        source="category.slug",
        read_only=True,
        allow_null=True,
    )
    borrowing_terms = serializers.SerializerMethodField()
    availability = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField())
    def get_borrowing_terms(self, product):
        from .public_terms import borrowing_terms
        return borrowing_terms(product, cache=self.context.setdefault("_borrowing_terms", {}))

    @extend_schema_field(AVAILABILITY_SCHEMA)
    def get_availability(self, product):
        return get_public_availability(product)

    @extend_schema_field({"type": "string", "format": "uri", "nullable": True})
    def get_image_url(self, product):
        return public_image_storage.public_url(product.image_key) or None


class PublicCategorySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    display_order = serializers.IntegerField(read_only=True)
    icon = serializers.CharField(read_only=True)
    product_count = serializers.IntegerField(read_only=True)


class PublicMakerspaceSerializer(serializers.Serializer):
    name = serializers.CharField(read_only=True)
    public_code = serializers.CharField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    location = serializers.CharField(read_only=True)
    map_url = serializers.CharField(read_only=True)
    logo_url = serializers.SerializerMethodField()
    cover_image_url = serializers.SerializerMethodField()

    @extend_schema_field({"type": "string", "format": "uri", "nullable": True})
    def get_logo_url(self, makerspace):
        return public_image_storage.public_url(makerspace.logo_key) or None

    @extend_schema_field({"type": "string", "format": "uri", "nullable": True})
    def get_cover_image_url(self, makerspace):
        return public_image_storage.public_url(makerspace.cover_image_key) or None


class PublicStatsBusiestPrinterSerializer(serializers.Serializer):
    name = serializers.CharField(read_only=True)
    model = serializers.CharField(read_only=True, allow_blank=True)
    hours = serializers.FloatField(read_only=True)
    completed = serializers.IntegerField(read_only=True)
    image_url = serializers.URLField(read_only=True, allow_null=True)


class PublicStatsPrinterSerializer(serializers.Serializer):
    name = serializers.CharField(read_only=True)
    model = serializers.CharField(read_only=True, allow_blank=True)
    jobs = serializers.IntegerField(read_only=True)
    hours = serializers.FloatField(read_only=True)
    grams = serializers.FloatField(read_only=True)
    image_url = serializers.URLField(read_only=True, allow_null=True)


class PublicStatsBrandSerializer(serializers.Serializer):
    brand = serializers.CharField(read_only=True)
    grams = serializers.FloatField(read_only=True)


class PublicStatsStatusCountsSerializer(serializers.Serializer):
    pending = serializers.IntegerField(read_only=True)
    accepted = serializers.IntegerField(read_only=True)
    printing = serializers.IntegerField(read_only=True)
    completed = serializers.IntegerField(read_only=True)
    collected = serializers.IntegerField(read_only=True)
    failed = serializers.IntegerField(read_only=True)
    rejected = serializers.IntegerField(read_only=True)


class PublicStatsQueueSerializer(serializers.Serializer):
    pending = serializers.IntegerField(read_only=True)
    accepted = serializers.IntegerField(read_only=True)
    printing = serializers.IntegerField(read_only=True)


class PublicStatsJobsSerializer(serializers.Serializer):
    completed = serializers.IntegerField(read_only=True)
    status_counts = PublicStatsStatusCountsSerializer(read_only=True)
    queue = PublicStatsQueueSerializer(read_only=True)


class PublicStatsFilamentTrendSerializer(serializers.Serializer):
    period = serializers.CharField(read_only=True)
    grams = serializers.FloatField(read_only=True)


class PublicStatsPrintingSerializer(serializers.Serializer):
    hours_all_time = serializers.FloatField(read_only=True)
    hours_this_month = serializers.FloatField(read_only=True)
    busiest_printer = PublicStatsBusiestPrinterSerializer(
        read_only=True,
        required=False,
        allow_null=True,
    )
    per_printer = PublicStatsPrinterSerializer(many=True, read_only=True)
    grams_all_time = serializers.FloatField(read_only=True)
    by_brand = PublicStatsBrandSerializer(many=True, read_only=True)
    jobs = PublicStatsJobsSerializer(read_only=True)
    filament_trend = PublicStatsFilamentTrendSerializer(many=True, read_only=True)


class PublicStatsPopularHardwareSerializer(serializers.Serializer):
    name = serializers.CharField(read_only=True)
    times_lent = serializers.IntegerField(read_only=True)
    total_quantity_lent = serializers.IntegerField(read_only=True)


class PublicStatsToolsOutSerializer(serializers.Serializer):
    name = serializers.CharField(read_only=True)
    quantity_out = serializers.IntegerField(read_only=True)


class PublicStatsLibrarySerializer(serializers.Serializer):
    currently_out_count = serializers.IntegerField(read_only=True)
    library_size = serializers.IntegerField(read_only=True)
    available_count = serializers.IntegerField(read_only=True)


class PublicStatsRecentlyAddedSerializer(serializers.Serializer):
    name = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class PublicStatsHardwareSerializer(serializers.Serializer):
    most_popular = PublicStatsPopularHardwareSerializer(many=True, read_only=True)
    tools_out = PublicStatsToolsOutSerializer(many=True, read_only=True)
    library = PublicStatsLibrarySerializer(read_only=True)
    recently_added = PublicStatsRecentlyAddedSerializer(many=True, read_only=True)


class PublicStatsCurrentLoanSerializer(serializers.Serializer):
    item_name = serializers.CharField(read_only=True)
    holder_name = serializers.CharField(read_only=True)
    due = serializers.DateTimeField(read_only=True, allow_null=True)
    since = serializers.DateTimeField(read_only=True, allow_null=True)


class PublicStatsMachinesSerializer(serializers.Serializer):
    usage_hours = serializers.FloatField(read_only=True)


class PublicStatsSerializer(serializers.Serializer):
    machines = PublicStatsMachinesSerializer(
        read_only=True,
        required=False,
        allow_null=True,
    )
    printing = PublicStatsPrintingSerializer(
        read_only=True,
        required=False,
        allow_null=True,
    )
    hardware = PublicStatsHardwareSerializer(read_only=True)
    current_loans = PublicStatsCurrentLoanSerializer(many=True, read_only=True)

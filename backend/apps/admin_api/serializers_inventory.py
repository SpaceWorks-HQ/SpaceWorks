from .serializers_inventory_products import (
    CREATE_PROTECTED_BUCKET_FIELDS,
    QUANTITY_BUCKET_FIELDS,
    CategoryAdminSerializer,
    InventoryProductAdminCreateSerializer,
    InventoryProductAdminSerializer,
    InventoryProductAdminUpdateSerializer,
)
from .serializers_inventory_assets import (
    InventoryAssetAdminSerializer,
    InventoryAssetAdminUpdateSerializer,
    InventoryAssetStatusActionSerializer,
    InventoryQuantityAdjustmentSerializer,
    NullableBoxPrimaryKeyRelatedField,
    PublicImageAttachRequestSerializer,
    PublicImageUploadRequestSerializer,
    PublicImageUploadResponseSerializer,
)

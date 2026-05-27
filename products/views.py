import logging
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Count, ExpressionWrapper, F, IntegerField, Q, Sum
from django.utils import timezone

from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminUser, IsAdminOrWorkerUser

from .inventory_services import create_stock_movement
from .models import (
    BundleItem,
    Category,
    KardexMovement,
    MTGCard,
    PricingSettings,
    PricingSource,
    Product,
    ProductTypeConfig,
    PurchaseOrder,
    PurchaseOrderItem,
    SingleCard,
    Supplier,
)
from .permissions import IsAdminOrWorkerOrReadOnly
from .purchase_order_import import parse_purchase_order_excel
from .purchase_order_product_services import (
    create_product_from_purchase_order_item,
    find_existing_single_product,
    find_existing_single_product_for_purchase_item,
    resolve_purchase_order_product_category,
)
from .purchase_order_services import (
    calculate_suggested_price_from_real_cost,
    receive_purchase_order,
    recalculate_purchase_order,
)
from .scryfall_normalizer import normalize_card_description
from .scryfall_service import search_scryfall_card
from .serializers import (
    BundleItemSerializer,
    CategorySerializer,
    KardexMovementSerializer,
    MTGCardSerializer,
    PricingSettingsSerializer,
    ProductPublicSerializer,
    ProductSerializer,
    ProductTypeConfigSerializer,
    PurchaseOrderItemSerializer,
    PurchaseOrderSerializer,
    SupplierSerializer,
)
from .services import (
    ScryfallServiceError,
    calculate_suggested_sale_price,
    extract_usd_price,
    get_active_pricing_settings,
    get_scryfall_card_by_id,
    import_card,
    import_catalog_from_xlsx,
    import_purchase_order_from_xlsx,
    search_cards,
)
from .throttles import ScryfallThrottle


logger = logging.getLogger(__name__)


CONDITION_MAP = {
    "NM": Product.CardCondition.NM,
    "MINT": Product.CardCondition.NM,
    "M": Product.CardCondition.NM,
    "EX": Product.CardCondition.LP,
    "EXCELLENT": Product.CardCondition.LP,
    "LP": Product.CardCondition.LP,
    "VG": Product.CardCondition.MP,
    "VERY GOOD": Product.CardCondition.MP,
    "MP": Product.CardCondition.MP,
    "HP": Product.CardCondition.HP,
    "DMG": Product.CardCondition.DMG,
    "DAMAGED": Product.CardCondition.DMG,
}


def _to_bool(value, default=False):
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in {
            "true",
            "1",
            "yes",
            "on",
            "si",
            "sí",
        }

    return bool(value)


def _normalize_condition(value):
    condition = str(value or "").strip().upper()

    if condition in CONDITION_MAP:
        return CONDITION_MAP[condition]

    raise ValidationError(f"Condición inválida: {value}")


def format_exception(exc):
    if hasattr(exc, "message_dict"):
        return exc.message_dict

    if hasattr(exc, "messages"):
        return exc.messages

    return str(exc)


def _card_image_from_scryfall(card_data):
    image_uris = card_data.get("image_uris") or {}
    faces = card_data.get("card_faces") or []

    face_images = {}

    if faces and isinstance(faces[0], dict):
        face_images = faces[0].get("image_uris") or {}

    image_large = (
        image_uris.get("large")
        or face_images.get("large")
        or image_uris.get("normal")
        or face_images.get("normal")
        or ""
    )
    image_normal = (
        image_uris.get("normal")
        or face_images.get("normal")
        or image_large
        or ""
    )
    image_small = (
        image_uris.get("small")
        or face_images.get("small")
        or image_normal
        or ""
    )

    return image_large, image_normal, image_small


def _update_or_create_mtg_card(card_data):
    image_large, image_normal, image_small = _card_image_from_scryfall(
        card_data)

    card, _ = MTGCard.objects.update_or_create(
        scryfall_id=card_data["id"],
        defaults={
            "name": card_data.get("name", ""),
            "printed_name": card_data.get("printed_name", ""),
            "set_code": card_data.get("set", ""),
            "set_name": card_data.get("set_name", ""),
            "collector_number": card_data.get("collector_number", ""),
            "rarity": card_data.get("rarity", ""),
            "mana_cost": card_data.get("mana_cost", ""),
            "type_line": card_data.get("type_line", ""),
            "oracle_text": card_data.get("oracle_text", ""),
            "colors": card_data.get("colors") or [],
            "color_identity": card_data.get("color_identity") or [],
            "image_large": image_large,
            "image_normal": image_normal,
            "image_small": image_small,
            "scryfall_uri": card_data.get("scryfall_uri", ""),
            "raw_data": card_data,
        },
    )

    return card


def _build_product_description_from_card(card):
    parts = []

    if card.type_line:
        parts.append(card.type_line)

    if card.rarity:
        parts.append(f"Rareza: {card.rarity}")

    if card.set_name:
        parts.append(f"Set: {card.set_name} ({card.set_code.upper()})")

    if card.collector_number:
        parts.append(f"Collector #: {card.collector_number}")

    if card.oracle_text:
        parts.append("")
        parts.append(card.oracle_text)

    return "\n".join(parts).strip()


class CardViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MTGCard.objects.all()
    serializer_class = MTGCardSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = [
        "name",
        "set_name",
        "set_code",
        "collector_number",
        "rarity",
    ]


class MTGScryfallViewSet(viewsets.ViewSet):
    def get_throttles(self):
        if self.action in ("search", "import_card_action"):
            return [ScryfallThrottle()]

        return super().get_throttles()

    def get_permissions(self):
        if self.action == "search":
            return [AllowAny()]

        if self.action == "import_card_action":
            return [IsAdminOrWorkerUser()]

        return [IsAdminUser()]

    @action(detail=False, methods=["get"], url_path="search")
    def search(self, request):
        query = request.query_params.get("q", "").strip()

        if not query:
            return Response(
                {"detail": "q es obligatorio."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            return Response({"results": search_cards(query)})
        except ScryfallServiceError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    @action(detail=False, methods=["post"], url_path="import")
    def import_card_action(self, request):
        scryfall_id = request.data.get("scryfall_id")

        if not scryfall_id:
            return Response(
                {"detail": "scryfall_id es obligatorio."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            card, _card_data = import_card(scryfall_id)
        except ScryfallServiceError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            MTGCardSerializer(card).data,
            status=status.HTTP_201_CREATED,
        )


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [IsAdminOrWorkerOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "name",
        "description",
        "single_card__mtg_card__name",
    ]
    ordering_fields = [
        "price_clp",
        "created_at",
        "updated_at",
        "name",
        "stock",
    ]
    parser_classes = [
        JSONParser,
        FormParser,
        MultiPartParser,
    ]

    def get_serializer_class(self):
        user = self.request.user
        if user and user.is_authenticated:
            from accounts.permissions import is_admin_user, is_worker_user
            if is_admin_user(user) or is_worker_user(user):
                return ProductSerializer
        return ProductPublicSerializer

    @action(
        detail=True,
        methods=["post"],
        url_path="bundle-items",
        permission_classes=[IsAdminOrWorkerUser],
    )
    def add_bundle_item(self, request, pk=None):
        """Agrega un componente al bundle."""
        bundle = self.get_object()

        if bundle.product_type != Product.ProductType.BUNDLE:
            return Response(
                {"detail": "Solo se pueden agregar items a productos de tipo bundle."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        item_id = request.data.get("item_id")

        if not item_id:
            return Response({"detail": "item_id es obligatorio."}, status=400)

        try:
            quantity = int(request.data.get("quantity", 1) or 1)
        except (TypeError, ValueError):
            return Response({"detail": "quantity debe ser un entero."}, status=400)

        if quantity < 1:
            return Response({"detail": "quantity debe ser mayor o igual a 1."}, status=400)

        try:
            item_product = Product.objects.get(pk=item_id)
        except Product.DoesNotExist:
            return Response({"detail": "Producto componente no encontrado."}, status=404)

        if item_product.product_type == Product.ProductType.BUNDLE:
            return Response(
                {"detail": "Un bundle no puede contener otro bundle."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if item_product.pk == bundle.pk:
            return Response(
                {"detail": "Un bundle no puede contenerse a sí mismo."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bundle_item, created = BundleItem.objects.get_or_create(
            bundle=bundle,
            item=item_product,
            defaults={"quantity": quantity},
        )

        if not created:
            bundle_item.quantity = quantity
            bundle_item.save(update_fields=["quantity"])

        return Response(
            BundleItemSerializer(bundle_item).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["delete"],
        url_path=r"bundle-items/(?P<item_id>[^/.]+)",
        permission_classes=[IsAdminOrWorkerUser],
    )
    def remove_bundle_item(self, request, pk=None, item_id=None):
        """Elimina un componente del bundle."""
        bundle = self.get_object()
        deleted, _ = BundleItem.objects.filter(bundle=bundle, item_id=item_id).delete()

        if not deleted:
            return Response({"detail": "Componente no encontrado."}, status=404)

        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        queryset = (
            Product.objects.select_related(
                "category",
                "product_type_config",
                "single_card__mtg_card",
                "sealed_product",
            )
            .prefetch_related(
                "bundle_items__item",
                "lots",
            )
            .all()
        )

        params = self.request.query_params

        if params.get("product_type"):
            queryset = queryset.filter(product_type=params["product_type"])
        if params.get("product_type_config"):
            queryset = queryset.filter(product_type_config_id=params["product_type_config"])

        if params.get("category"):
            queryset = queryset.filter(category_id=params["category"])

        if params.get("active") in {"true", "false"}:
            queryset = queryset.filter(is_active=params["active"] == "true")

        if params.get("available") == "true":
            queryset = queryset.filter(
                is_active=True,
                price_clp__gt=0,
            ).filter(
                stock__gt=models.F("stock_reserved"),
            )

        if params.get("profitable") == "true":
            queryset = queryset.exclude(
                last_purchase_cost_clp__gt=0,
                price_clp__lt=models.F("last_purchase_cost_clp"),
            )

        if params.get("rarity"):
            queryset = queryset.filter(
                single_card__mtg_card__rarity__iexact=params["rarity"]
            )

        return queryset

    @action(
        detail=False,
        methods=["post"],
        url_path="create-single-from-scryfall",
        permission_classes=[IsAdminUser],
    )
    def create_single_from_scryfall(self, request):
        required_fields = [
            "scryfall_id",
            "category_id",
            "price_clp",
            "condition",
            "language",
        ]
        payload = request.data or {}
        errors = {}

        for field in required_fields:
            if payload.get(field) in (None, ""):
                errors[field] = "Este campo es obligatorio."

        if errors:
            return Response(
                {
                    "detail": "Payload inválido.",
                    "errors": errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            category_id = int(payload.get("category_id"))
            price_clp = int(payload.get("price_clp", 0))
            stock = int(payload.get("stock", 0) or 0)
            is_foil = _to_bool(payload.get("is_foil", False))
            is_active = _to_bool(payload.get("is_active", True), default=True)
            condition = _normalize_condition(payload.get("condition"))
            language = str(payload.get("language", "")).strip().upper()
            notes = str(payload.get("notes", "") or "").strip()
            scryfall_id = str(payload.get("scryfall_id", "")).strip()
        except (TypeError, ValueError, ValidationError) as exc:
            return Response(
                {
                    "detail": "Payload inválido.",
                    "error": format_exception(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if price_clp < 0:
            return Response(
                {
                    "detail": "price_clp no puede ser menor a 0.",
                    "errors": {"price_clp": "Debe ser mayor o igual a 0."},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if stock < 0:
            return Response(
                {
                    "detail": "stock no puede ser menor a 0.",
                    "errors": {"stock": "Debe ser mayor o igual a 0."},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        category = Category.objects.filter(pk=category_id).first()

        if not category:
            return Response(
                {
                    "detail": "category_id inválido.",
                    "errors": {
                        "category_id": "No existe la categoría indicada."
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            card_data = get_scryfall_card_by_id(scryfall_id)
            card = _update_or_create_mtg_card(card_data)
            usd_ref = extract_usd_price(card_data, is_foil=is_foil)
            existing_product, warning = find_existing_single_product(
                mtg_card=card,
                condition=condition,
                language=language,
                is_foil=is_foil,
            )
            if warning:
                return Response(
                    {"detail": f"No se pudo seleccionar producto existente: {warning}."},
                    status=status.HTTP_409_CONFLICT,
                )
            if existing_product:
                return Response(
                    {
                        "id": existing_product.id,
                        "name": existing_product.name,
                        "price_clp": existing_product.price_clp,
                        "stock": existing_product.stock,
                        "mtg_card": existing_product.single_card.mtg_card_id,
                        "image": existing_product.image,
                        "category": existing_product.category_id,
                        "created": False,
                        "reused": True,
                    },
                    status=status.HTTP_200_OK,
                )

            with transaction.atomic():
                product = Product.objects.create(
                    category=category,
                    name=(
                        f"{card.name} - "
                        f"{card.set_code.upper()} "
                        f"#{card.collector_number}"
                    ),
                    description=_build_product_description_from_card(card),
                    price_clp=price_clp,
                    stock=stock,
                    notes=notes,
                    is_active=is_active,
                    product_type=Product.ProductType.SINGLE,
                    image=card.image_large or card.image_normal or card.image_small,
                )

                SingleCard.objects.create(
                    product=product,
                    mtg_card=card,
                    condition=condition,
                    language=language,
                    is_foil=is_foil,
                    edition=card.set_name,
                    price_usd_reference=usd_ref,
                )

        except ValidationError as exc:
            logger.error(
                "Error consultando Scryfall scryfall_id=%s error=%s",
                scryfall_id,
                exc,
                exc_info=True,
            )
            return Response(
                {
                    "detail": "No se pudo obtener la carta desde Scryfall usando el ID recibido.",
                    "scryfall_id": scryfall_id,
                    "scryfall_response": format_exception(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ScryfallServiceError as exc:
            return Response(
                {
                    "detail": "No se pudo obtener la carta desde Scryfall.",
                    "scryfall_id": scryfall_id,
                    "scryfall_response": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "id": product.id,
                "name": product.name,
                "price_clp": product.price_clp,
                "stock": product.stock,
                "mtg_card": product.single_card.mtg_card_id,
                "image": product.image,
                "category": product.category_id,
            },
            status=status.HTTP_201_CREATED,
        )


    @action(
        detail=False,
        methods=["post"],
        url_path="recalculate-prices",
        permission_classes=[IsAdminUser],
    )
    def recalculate_prices(self, request):
        payload = request.data or {}
        apply_to_sale_price = _to_bool(payload.get("apply_to_sale_price"), False)
        only_active = _to_bool(payload.get("only_active"), False)
        only_with_stock = _to_bool(payload.get("only_with_stock"), False)
        only_negative_margin = _to_bool(payload.get("only_negative_margin"), False)
        category_id = payload.get("category_id")
        product_type = (payload.get("product_type") or "").strip()
        mode = (payload.get("mode") or "real_cost").strip()
        allowed_modes = {"real_cost", "current_usd"}
        if mode not in allowed_modes:
            return Response({"detail": "mode inválido. Usa real_cost o current_usd."}, status=status.HTTP_400_BAD_REQUEST)

        pricing_settings = PricingSettings.objects.filter(is_active=True).order_by("-updated_at", "-id").first()
        if not pricing_settings:
            return Response({"detail": "No hay una configuración de precios activa."}, status=status.HTTP_400_BAD_REQUEST)

        if Decimal(str(pricing_settings.margin_factor or 0)) <= Decimal("1"):
            return Response({"detail": "margin_factor debe ser mayor a 1 para recalcular precios."}, status=status.HTTP_400_BAD_REQUEST)

        queryset = Product.objects.all().order_by("id")
        if only_active:
            queryset = queryset.filter(is_active=True)
        if only_with_stock:
            queryset = queryset.filter(stock__gt=0)
        if category_id not in (None, ""):
            queryset = queryset.filter(category_id=category_id)
        if product_type:
            queryset = queryset.filter(product_type=product_type)
        if only_negative_margin:
            queryset = queryset.filter(
                Q(price_clp__lt=F("last_purchase_cost_clp"))
                | Q(last_purchase_cost_clp__gt=0, price_clp__lt=F("average_cost_clp"))
            )

        processed_count = queryset.count()
        updated_count = 0
        skipped_count = 0
        negative_before = 0
        negative_after = 0
        warnings = []
        results = []

        rounding_to = int(pricing_settings.rounding_to or 100)
        usd_to_clp = Decimal(str(pricing_settings.usd_to_clp or 0))
        if rounding_to <= 0:
            rounding_to = 100
            warnings.append("rounding_to inválido en configuración activa. Se usó 100 por defecto.")

        for product in queryset:
            cost_real = int(product.cost_real_clp or 0)
            fallback_cost = int(product.last_purchase_cost_clp or product.average_cost_clp or 0)
            usd_reference = None

            if mode == "current_usd":
                if hasattr(product, "single_card") and product.single_card:
                    usd_reference = Decimal(str(product.single_card.price_usd_reference or 0))
                if (usd_reference is None or usd_reference <= 0) and Decimal(str(product.price_external_usd or 0)) > 0:
                    usd_reference = Decimal(str(product.price_external_usd or 0))

                if usd_reference is None or usd_reference <= 0:
                    skipped_count += 1
                    warnings.append(f"Producto {product.id} sin USD de referencia, no se puede recalcular en mode=current_usd.")
                    results.append({"product_id": product.id, "name": product.name, "status": "skipped", "mode": mode})
                    continue

                if usd_to_clp <= 0:
                    return Response({"detail": "usd_to_clp debe ser mayor a 0 para mode=current_usd."}, status=status.HTTP_400_BAD_REQUEST)

                base_cost_decimal = usd_reference * usd_to_clp
                base_cost = int(base_cost_decimal.quantize(Decimal("1")))
            else:
                base_cost = cost_real if cost_real > 0 else fallback_cost

            if base_cost <= 0:
                skipped_count += 1
                warnings.append(f"Producto {product.id} sin costo base, no se puede calcular precio sugerido.")
                results.append({"product_id": product.id, "name": product.name, "status": "skipped", "mode": mode})
                continue

            old_price = int(product.price_clp or 0)
            old_suggested = int(product.suggested_price_clp or 0)
            if old_price < base_cost:
                negative_before += 1

            if mode == "current_usd":
                raw = Decimal(str(base_cost))
                raw *= Decimal(str(pricing_settings.import_factor or 1))
                raw *= Decimal(str(pricing_settings.risk_factor or 1))
                raw *= Decimal(str(pricing_settings.margin_factor or 1))
                new_suggested = int((raw / Decimal(str(rounding_to))).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal(str(rounding_to)))
            else:
                new_suggested = int(calculate_suggested_price_from_real_cost(base_cost) or 0)

            if new_suggested < base_cost:
                new_suggested = base_cost

            if apply_to_sale_price:
                product.price_clp = max(new_suggested, base_cost)

            update_fields = ["price_clp", "updated_at"] if apply_to_sale_price else ["updated_at"]
            product.save(update_fields=update_fields)
            updated_count += 1

            new_margin = int(product.price_clp or 0) - base_cost
            if int(product.price_clp or 0) < base_cost:
                negative_after += 1

            results.append({
                "product_id": product.id,
                "name": product.name,
                "mode": mode,
                "usd_to_clp": float(usd_to_clp) if mode == "current_usd" else None,
                "cost_real_clp": cost_real,
                "base_cost_clp": base_cost,
                "usd_reference": float(usd_reference) if usd_reference is not None else None,
                "old_price_clp": old_price,
                "old_suggested_price_clp": old_suggested,
                "new_suggested_price_clp": new_suggested,
                "new_margin_clp": new_margin,
                "status": "updated",
            })

        return Response({
            "mode": mode,
            "usd_to_clp_used": float(usd_to_clp) if mode == "current_usd" else None,
            "processed_count": processed_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "applied_to_sale_price": apply_to_sale_price,
            "settings_id": pricing_settings.id,
            "negative_margin_before": negative_before,
            "negative_margin_after": negative_after,
            "results": results[:200],
            "warnings": warnings,
        })

    @action(
        detail=True,
        methods=["get"],
        url_path="suggested-price",
        permission_classes=[IsAdminUser],
    )
    def suggested_price(self, request, pk=None):
        product = self.get_object()
        unit_cost_clp = request.query_params.get("unit_cost_clp", 0)

        try:
            unit_cost_clp = int(float(unit_cost_clp or 0))
        except (TypeError, ValueError):
            return Response(
                {"detail": "unit_cost_clp inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            calculate_suggested_sale_price(
                product,
                unit_cost_clp=unit_cost_clp,
            )
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="apply-suggested-price",
        permission_classes=[IsAdminOrWorkerUser],
    )
    def apply_suggested_price(self, request, pk=None):
        product = self.get_object()
        # Fuente única de verdad para sugerido: property sugerida del modelo.
        suggested_price = int(product.suggested_price_clp or 0)

        if suggested_price <= 0:
            return Response(
                {"detail": "El producto no tiene precio sugerido válido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        product.price_clp = suggested_price
        if int(product.last_purchase_cost_clp or 0) > 0 and suggested_price < int(product.last_purchase_cost_clp or 0):
            product.is_active = False
        product.save(update_fields=["price_clp", "is_active", "updated_at"])

        return Response(self.get_serializer(product).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="sync-external-price",
        permission_classes=[IsAdminOrWorkerUser],
    )
    def sync_external_price(self, request, pk=None):
        product = self.get_object()
        exchange_rate = request.data.get("exchange_rate_usd_clp")

        try:
            exchange_rate = Decimal(str(exchange_rate))
        except Exception:
            return Response(
                {"detail": "exchange_rate_usd_clp inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not hasattr(product, "single_card") or not product.single_card:
            return Response(
                {"detail": "El producto no tiene datos de carta para sincronizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not product.single_card.mtg_card_id:
            return Response(
                {"detail": "El producto no tiene carta MTG asociada."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            card_data = get_scryfall_card_by_id(product.single_card.mtg_card.scryfall_id)
            usd_price = extract_usd_price(card_data, is_foil=product.single_card.is_foil)

            product.price_external_usd = Decimal(str(usd_price or 0))
            product.exchange_rate_usd_clp = Decimal(str(exchange_rate or 0))
            product.pricing_source = PricingSource.SCRYFALL
            product.pricing_last_update = timezone.now()
            product.save(
                update_fields=[
                    "price_external_usd",
                    "exchange_rate_usd_clp",
                    "pricing_source",
                    "pricing_last_update",
                    "updated_at",
                ]
            )
        except Exception as exc:
            return Response(
                {"detail": f"Error al sincronizar precio externo: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "detail": "Sincronización completada.",
                "product_id": product.id,
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="kardex",
        permission_classes=[IsAdminOrWorkerUser],
    )
    def kardex(self, request, pk=None):
        product = self.get_object()
        movements = product.kardex_movements.all()[:50]

        return Response(
            KardexMovementSerializer(
                movements,
                many=True,
            ).data
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="import-catalog-xlsx",
        permission_classes=[IsAdminOrWorkerUser],
        parser_classes=[MultiPartParser, FormParser],
    )
    def import_catalog_xlsx(self, request):
        excel_file = request.FILES.get("file")

        if not excel_file:
            return Response(
                {"detail": "Debes adjuntar un archivo .xlsx."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            summary = import_catalog_from_xlsx(excel_file)

            return Response(summary, status=status.HTTP_200_OK)

        except ValidationError as exc:
            return Response(
                {
                    "detail": "Error procesando archivo.",
                    "error": format_exception(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as exc:
            logger.exception("Error inesperado importando catálogo XLSX.")
            return Response(
                {
                    "detail": "Error procesando archivo.",
                    "error": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


class KardexViewSet(viewsets.GenericViewSet):
    serializer_class = KardexMovementSerializer
    permission_classes = [IsAdminOrWorkerUser]

    def get_queryset(self):
        queryset = KardexMovement.objects.select_related(
            "product",
            "created_by",
        )

        product_id = self.request.query_params.get("product_id")

        if product_id:
            queryset = queryset.filter(product_id=product_id)

        movement_type = self.request.query_params.get("movement_type")

        if movement_type:
            queryset = queryset.filter(movement_type=movement_type)

        date_from = self.request.query_params.get("date_from")

        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)

        date_to = self.request.query_params.get("date_to")

        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        supplier_id = self.request.query_params.get("supplier_id")

        if supplier_id:
            purchase_order_ids = PurchaseOrder.objects.filter(
                supplier_id=supplier_id,
            ).values_list(
                "id",
                flat=True,
            )

            queryset = queryset.filter(
                reference_type="PURCHASE_ORDER",
                reference_id__in=[
                    str(po_id)
                    for po_id in purchase_order_ids
                ],
            )

        return queryset.order_by("-created_at", "-id")

    def list(self, request):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(
                self.get_serializer(
                    page,
                    many=True,
                ).data
            )

        return Response(
            self.get_serializer(
                queryset,
                many=True,
            ).data
        )

    @action(detail=False, methods=["post"], url_path="movement")
    def movement(self, request):
        payload = request.data
        product = Product.objects.filter(pk=payload.get("product")).first()

        if not product:
            return Response(
                {"detail": "product inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            quantity = int(payload.get("quantity", 0))

            if quantity <= 0:
                return Response(
                    {"detail": "quantity debe ser mayor a 0."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            movement = create_stock_movement(
                product=product,
                movement_type=payload.get("movement_type"),
                quantity=quantity,
                created_by=request.user,
                unit_cost_clp=int(payload.get("unit_cost_clp", 0) or 0),
                unit_price_clp=int(payload.get("unit_price_clp", 0) or 0),
                reference_label=payload.get("reference_label", ""),
                reference_type=payload.get("reference_type", "manual"),
                reference_id=payload.get("reference_id", ""),
                notes=payload.get("notes", ""),
            )

        except (TypeError, ValueError, ValidationError) as exc:
            return Response(
                {"detail": format_exception(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            self.get_serializer(movement).data,
            status=status.HTTP_201_CREATED,
        )


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrWorkerOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = [
        "name",
        "slug",
    ]

    def get_queryset(self):
        queryset = (
            Category.objects.annotate(
                products_count=Count("products"),
            )
            .order_by("sort_order", "name")
        )
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() in {"1", "true", "yes"})
        return queryset


class ProductTypeConfigViewSet(viewsets.ModelViewSet):
    serializer_class = ProductTypeConfigSerializer
    permission_classes = [IsAdminOrWorkerOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "slug", "description"]

    def get_queryset(self):
        queryset = ProductTypeConfig.objects.all().order_by("sort_order", "name")
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() in {"1", "true", "yes"})

        user = getattr(self.request, "user", None)
        is_admin_or_worker = (
            user
            and user.is_authenticated
            and hasattr(user, "profile")
            and user.profile.role in ("admin", "worker")
        )
        if not is_admin_or_worker:
            queryset = queryset.exclude(slug__in=["service", "other"])

        return queryset


class PricingSettingsViewSet(viewsets.ModelViewSet):
    serializer_class = PricingSettingsSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        return PricingSettings.objects.order_by("-updated_at")

    def _ensure_single_active(self, instance):
        if instance.is_active:
            PricingSettings.objects.exclude(pk=instance.pk).update(
                is_active=False,
            )

    def perform_create(self, serializer):
        instance = serializer.save()
        self._ensure_single_active(instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        self._ensure_single_active(instance)

    @action(
        detail=False,
        methods=["get"],
        url_path="active",
        permission_classes=[IsAdminOrWorkerUser],
    )
    def active(self, request):
        active_settings = get_active_pricing_settings()

        return Response(
            {
                "usd_to_clp": active_settings.usd_to_clp,
                "import_factor": active_settings.import_factor,
                "risk_factor": active_settings.risk_factor,
                "margin_factor": active_settings.margin_factor,
                "rounding_to": active_settings.rounding_to,
            }
        )


class SupplierViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    permission_classes = [IsAdminOrWorkerUser]

    def get_queryset(self):
        return Supplier.objects.order_by("name")


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAdminOrWorkerUser]
    parser_classes = [
        JSONParser,
        FormParser,
        MultiPartParser,
    ]

    def get_queryset(self):
        queryset = (
            PurchaseOrder.objects
            .select_related("supplier", "created_by")
            .prefetch_related("items", "items__product")
            .order_by("-created_at", "-id")
        )

        supplier_id = self.request.query_params.get("supplier_id")
        status_param = self.request.query_params.get("status")
        product_id = self.request.query_params.get("product_id")

        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)

        if status_param:
            queryset = queryset.filter(status=status_param)

        if product_id:
            queryset = queryset.filter(items__product_id=product_id).distinct()

        return queryset

    def _generate_order_number(self):
        date_prefix = timezone.localdate().strftime("%Y%m%d")
        base = f"PO-{date_prefix}-"

        last_po = (
            PurchaseOrder.objects.filter(
                order_number__startswith=base,
            )
            .order_by("-order_number")
            .first()
        )

        sequence = (
            int(last_po.order_number.split("-")[-1]) + 1
            if last_po
            else 1
        )

        return f"{base}{sequence:04d}"

    def _get_exchange_rate_for_currency(self, currency):
        currency = str(currency or "CLP").upper()

        if currency == "CLP":
            return Decimal("1")

        if currency == "USD":
            pricing_settings = (
                PricingSettings.objects
                .filter(is_active=True)
                .order_by("-updated_at", "-id")
                .first()
            )

            if not pricing_settings:
                raise ValidationError(
                    "No existe una configuración de precios activa para obtener el valor USD → CLP."
                )

            usd_to_clp = Decimal(str(pricing_settings.usd_to_clp or 0))

            if usd_to_clp <= 0:
                raise ValidationError(
                    "El valor USD → CLP configurado debe ser mayor a 0."
                )

            return usd_to_clp

        raise ValidationError(
            f"Moneda no soportada para orden de compra: {currency}"
        )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def _match_item_with_scryfall(
        self,
        item,
        normalized_name=None,
        set_name=None,
    ):
        normalized_name = (
            normalized_name
            or item.normalized_card_name
            or normalize_card_description(item.raw_description)["normalized_card_name"]
        )
        set_name = (
            set_name
            if set_name is not None
            else item.set_name_detected
        )

        scryfall_data = item.scryfall_data or {}
        is_foil = bool(scryfall_data.get("is_foil_detected", False))
        language = str(scryfall_data.get("language", "EN")).upper()

        result = search_scryfall_card(
            normalized_name,
            set_hint=set_name,
            is_foil=is_foil,
        )

        if not result.get("found"):
            return {
                "status": result.get("status", "not_found"),
                "message": result.get("message", "No encontrado."),
                "result": result,
            }

        condition = _normalize_condition(item.style_condition)

        item.normalized_card_name = normalized_name
        item.set_name_detected = set_name or item.set_name_detected
        item.style_condition = condition
        item.scryfall_id = result["scryfall_id"]
        item.scryfall_data = result
        product = find_existing_single_product_for_purchase_item(item)

        if product:
            item.product = product
            update_fields = [
                "normalized_card_name",
                "set_name_detected",
                "style_condition",
                "scryfall_id",
                "scryfall_data",
                "product",
            ]
        else:
            update_fields = [
                "normalized_card_name",
                "set_name_detected",
                "style_condition",
                "scryfall_id",
                "scryfall_data",
            ]

        item.save(update_fields=update_fields)

        return {
            "status": "matched",
            "message": "ok",
            "result": result,
            "product_id": product.id if product else None,
        }

    @action(detail=False, methods=["post"], url_path="import-preview")
    def import_preview(self, request):
        excel_file = request.FILES.get("file")

        if not excel_file:
            return Response(
                {"detail": "Debes adjuntar un archivo .xlsx."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parsed = parse_purchase_order_excel(
            excel_file,
            fallback_currency=request.data.get("original_currency", "USD"),
        )

        items = parsed.get("items", [])
        condition_counts = {}
        items_sum = Decimal("0")

        for item in items:
            condition = item.get("style_condition", "NM")
            condition_counts[condition] = condition_counts.get(
                condition, 0) + 1
            items_sum += Decimal(item.get("line_total_original", "0"))

        return Response(
            {
                "source_store": request.data.get("source_store", "Card Kingdom"),
                "supplier_id": request.data.get("supplier_id"),
                "currency": parsed.get("currency"),
                "detected_currency": parsed.get("currency"),
                "totals": parsed.get("totals"),
                "items": items,
                "items_count_by_condition": condition_counts,
                "items_calculated_sum": f"{items_sum.quantize(Decimal('0.01'))}",
                "warnings": parsed.get("warnings", []),
                "errors": parsed.get("errors", []),
            }
        )

    @action(detail=True, methods=["post"], url_path="receive")
    def receive(self, request, pk=None):
        purchase_order = self.get_object()

        try:
            purchase_order = receive_purchase_order(
                purchase_order,
                request.user,
            )
        except ValidationError as exc:
            return Response(
                {"detail": format_exception(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            self.get_serializer(purchase_order).data
        )

    @action(detail=True, methods=["post"], url_path="recalculate")
    def recalculate(self, request, pk=None):
        purchase_order = self.get_object()

        try:
            purchase_order = recalculate_purchase_order(purchase_order)
            purchase_order.refresh_from_db()
        except ValidationError as exc:
            return Response(
                {"detail": format_exception(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "subtotal_clp": purchase_order.subtotal_clp,
                "total_extra_costs_clp": purchase_order.total_extra_costs_clp,
                "grand_total_clp": purchase_order.grand_total_clp,
                "items": PurchaseOrderItemSerializer(
                    purchase_order.items.all(),
                    many=True,
                ).data,
            }
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="scryfall-match",
    )
    def scryfall_match(self, request, pk=None):
        purchase_order = self.get_object()
        item_id = request.data.get("item_id")

        try:
            item = purchase_order.items.get(id=item_id)
        except PurchaseOrderItem.DoesNotExist:
            return Response(
                {"detail": "Item no encontrado en la orden."},
                status=status.HTTP_404_NOT_FOUND,
            )

        name = request.data.get("normalized_card_name")
        set_name = request.data.get("set_name_detected")

        try:
            output = self._match_item_with_scryfall(
                item,
                normalized_name=name,
                set_name=set_name,
            )
        except ValidationError as exc:
            return Response(
                {"detail": format_exception(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if output["status"] != "matched":
            return Response(
                {
                    "scryfall_match_status": output["status"],
                    "scryfall_match_message": output["message"],
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        item.refresh_from_db()
        data = PurchaseOrderItemSerializer(item).data
        data["scryfall_match_status"] = "matched"
        data["scryfall_match_message"] = (
            "Carta vinculada"
            if output.get("product_id")
            else "Carta encontrada, sin producto vinculado"
        )

        return Response(data)

    @action(detail=False, methods=["post"], url_path="import-create")
    def import_create(self, request):
        excel_file = request.FILES.get("file")

        if not excel_file:
            return Response(
                {"detail": "Debes adjuntar un archivo .xlsx."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            parsed = parse_purchase_order_excel(
                excel_file,
                fallback_currency=request.data.get("original_currency", "USD"),
            )
        except ValidationError as exc:
            return Response(
                {"detail": format_exception(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        supplier = None
        supplier_id = request.data.get("supplier_id")
        supplier_name = (request.data.get("supplier_name") or "").strip()

        if supplier_id:
            supplier = Supplier.objects.filter(id=supplier_id).first()
        elif supplier_name:
            supplier, _ = Supplier.objects.get_or_create(name=supplier_name)

        if not supplier:
            return Response(
                {"detail": "supplier_id o supplier_name es obligatorio."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        auto_match = _to_bool(
            request.data.get("auto_match_scryfall"),
            True,
        )
        create_missing_products = _to_bool(
            request.data.get("create_missing_products"),
            False,
        )
        activate_products = _to_bool(
            request.data.get("activate_products"),
            False,
        )

        # Fase 1: persistimos orden + ítems dentro de una transacción corta
        # (sin requests HTTP externos para evitar locks largos).
        with transaction.atomic():
            currency = str(parsed.get("currency") or "USD").upper()
            exchange_rate = self._get_exchange_rate_for_currency(currency)
            # Si el usuario envió un valor de envío manual, reemplaza al detectado del Excel
            shipping_override_clp = int(request.data.get("shipping_clp_override") or 0)
            shipping_original_value = Decimal(parsed["totals"]["shipping_original"])

            purchase_order = PurchaseOrder.objects.create(
                supplier=supplier,
                order_number=self._generate_order_number(),
                created_by=request.user,
                source_store=request.data.get("source_store", "Card Kingdom"),
                status=PurchaseOrder.Status.DRAFT,
                purchase_order_type=PurchaseOrder.PurchaseOrderType.SINGLES,
                original_currency=currency,
                exchange_rate_snapshot_clp=exchange_rate,
                subtotal_original=Decimal(
                    parsed["totals"]["subtotal_original"]),
                shipping_original=shipping_original_value,
                shipping_clp=shipping_override_clp if shipping_override_clp > 0 else 0,
                sales_tax_original=Decimal(
                    parsed["totals"]["sales_tax_original"]),
                total_original=Decimal(parsed["totals"]["total_original"]),
                import_duties_clp=int(
                    request.data.get("import_duties_clp") or 0),
                customs_fee_clp=int(request.data.get("customs_fee_clp") or 0),
                handling_fee_clp=int(
                    request.data.get("handling_fee_clp") or 0),
                paypal_variation_clp=int(
                    request.data.get("paypal_variation_clp") or 0),
                other_costs_clp=int(request.data.get("other_costs_clp") or 0),
                update_prices_on_receive=_to_bool(
                    request.data.get("update_prices_on_receive"),
                    False,
                ),
            )

            created_items = []

            for item_data in parsed.get("items", []):
                item = PurchaseOrderItem.objects.create(
                    purchase_order=purchase_order,
                    raw_description=item_data["raw_description"],
                    normalized_card_name=item_data["normalized_card_name"],
                    set_name_detected=item_data["set_name_detected"],
                    style_condition=_normalize_condition(
                        item_data["style_condition"]
                    ),
                    quantity_ordered=item_data["quantity_ordered"],
                    unit_price_original=Decimal(
                        item_data["unit_price_original"]),
                    line_total_original=Decimal(
                        item_data["line_total_original"]),
                    scryfall_data={
                        "is_foil_detected": item_data.get(
                            "is_foil_detected",
                            False,
                        ),
                        "language": item_data.get("language", "EN"),
                    },
                )

                created_items.append(item)

        # Fase 2: fuera de transaction.atomic, hacemos matching con Scryfall.
        for item in created_items:
            if auto_match:
                try:
                    self._match_item_with_scryfall(item)
                except Exception as exc:
                    logger.warning(
                        "No se pudo hacer match Scryfall item_id=%s error=%s",
                        item.id,
                        exc,
                    )

            if not item.product_id:
                existing_product = find_existing_single_product_for_purchase_item(
                    item
                )
                if existing_product:
                    item.product = existing_product
                    item.save(update_fields=["product"])

        if create_missing_products:
            category = resolve_purchase_order_product_category(None)

            for item in purchase_order.items.filter(product__isnull=True):
                try:
                    product, _ = create_product_from_purchase_order_item(
                        item,
                        category=category,
                        created_by=request.user,
                    )

                    if activate_products:
                        product.is_active = True
                        product.save(update_fields=["is_active"])
                except Exception as exc:
                    logger.warning(
                        "No se pudo crear producto desde item_id=%s error=%s",
                        item.id,
                        exc,
                    )

        # Segunda transacción corta: recalcular totales finales.
        with transaction.atomic():
            recalculate_purchase_order(purchase_order)
            purchase_order.refresh_from_db()

        return Response(
            PurchaseOrderSerializer(purchase_order).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"items/(?P<item_id>[^/.]+)/create-product",
    )
    def create_product_from_item(self, request, pk=None, item_id=None):
        purchase_order = self.get_object()

        try:
            item = purchase_order.items.get(id=item_id)
        except PurchaseOrderItem.DoesNotExist:
            return Response(
                {"detail": "Item no encontrado en la orden."},
                status=status.HTTP_404_NOT_FOUND,
            )

        category = None
        category_id = request.data.get("category_id")

        if category_id:
            category = Category.objects.filter(id=category_id).first()

            if not category:
                return Response(
                    {"detail": "category_id inválido."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        category = resolve_purchase_order_product_category(category)
        activate_product = _to_bool(
            request.data.get("activate_product"),
            False,
        )

        try:
            product, created = create_product_from_purchase_order_item(
                item,
                category=category,
                created_by=request.user,
            )
        except ValidationError as exc:
            return Response(
                {"detail": format_exception(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if activate_product and product:
            product.is_active = True
            product.save(update_fields=["is_active"])

        item.refresh_from_db()

        return Response(
            {
                "item": PurchaseOrderItemSerializer(item).data,
                "product_id": product.id,
                "product_name": product.name,
                "created": created,
            }
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"items/(?P<item_id>[^/.]+)/link-product",
    )
    def link_product(self, request, pk=None, item_id=None):
        purchase_order = self.get_object()

        try:
            item = purchase_order.items.get(id=item_id)
        except PurchaseOrderItem.DoesNotExist:
            return Response(
                {"detail": "Item no encontrado en la orden."},
                status=status.HTTP_404_NOT_FOUND,
            )

        product_id = request.data.get("product_id")
        product = Product.objects.filter(id=product_id).first()

        if not product:
            return Response(
                {"detail": "product_id inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        item.product = product
        item.save(update_fields=["product"])

        return Response(
            {
                "item_id": item.id,
                "product_id": product.id,
                "status": "linked",
            }
        )

    @action(detail=True, methods=["post"], url_path="create-missing-products")
    def create_missing_products(self, request, pk=None):
        purchase_order = self.get_object()

        if purchase_order.purchase_order_type == PurchaseOrder.PurchaseOrderType.GENERAL:
            missing_without_product = purchase_order.items.filter(product__isnull=True).exists()
            if missing_without_product:
                return Response(
                    {"detail": "Las órdenes generales deben seleccionar productos existentes desde el mantenedor."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "purchase_order_id": purchase_order.id,
                    "created_count": 0,
                    "linked_existing_count": 0,
                    "failed_count": 0,
                    "results": [],
                }
            )

        category = None
        category_id = request.data.get("category_id")

        if category_id:
            category = Category.objects.filter(id=category_id).first()

            if not category:
                return Response(
                    {"detail": "category_id inválido."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        category = resolve_purchase_order_product_category(category)
        activate_products = _to_bool(
            request.data.get("activate_products"),
            False,
        )

        items = list(
            purchase_order.items.filter(product__isnull=True)
            .order_by("id")
        )

        results = []
        created_count = 0
        linked_existing_count = 0
        failed_count = 0

        for item in items:
            try:
                existing_product = find_existing_single_product_for_purchase_item(item)
                if existing_product:
                    item.product = existing_product
                    item.save(update_fields=["product"])
                    linked_existing_count += 1
                    results.append(
                        {
                            "item_id": item.id,
                            "status": "linked_existing",
                            "product_id": existing_product.id,
                            "product_name": existing_product.name,
                        }
                    )
                    continue

                product, created = create_product_from_purchase_order_item(
                    item,
                    category=category,
                    created_by=request.user,
                )

                if activate_products:
                    product.is_active = True
                    product.save(update_fields=["is_active"])

                status_label = "created" if created else "linked_existing"

                if created:
                    created_count += 1
                else:
                    linked_existing_count += 1

                results.append(
                    {
                        "item_id": item.id,
                        "status": status_label,
                        "product_id": product.id,
                        "product_name": product.name,
                    }
                )

            except Exception as exc:
                failed_count += 1
                results.append(
                    {
                        "item_id": item.id,
                        "status": "error",
                        "message": str(exc),
                    }
                )

        return Response(
            {
                "purchase_order_id": purchase_order.id,
                "created_count": created_count,
                "linked_existing_count": linked_existing_count,
                "failed_count": failed_count,
                "results": results,
            }
        )

    @action(detail=True, methods=["post"], url_path="apply-suggested-prices")
    def apply_suggested_prices(self, request, pk=None):
        purchase_order = self.get_object()

        items = list(purchase_order.items.all())
        for item in items:
            item.sale_price_to_apply_clp = item.suggested_sale_price_clp
        PurchaseOrderItem.objects.bulk_update(
            items,
            ["sale_price_to_apply_clp"],
        )

        return Response(self.get_serializer(purchase_order).data)

    @action(detail=False, methods=["post"], url_path="import")
    def import_purchase_order(self, request):
        excel_file = request.FILES.get("file")

        if not excel_file:
            return Response(
                {"detail": "Debes adjuntar un archivo .xlsx."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            parsed = parse_purchase_order_excel(excel_file)
        except Exception as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "preview": parsed.get("items", []),
                "errors": parsed.get("errors", []),
                "totals": parsed.get("totals", {}),
                "currency": parsed.get("currency", "CLP"),
            }
        )

    @action(detail=False, methods=["post"], url_path="import-xlsx")
    def import_xlsx(self, request):
        excel_file = request.FILES.get("file")

        if not excel_file:
            return Response(
                {"detail": "Debes adjuntar un archivo .xlsx."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        purchase_order_id = request.data.get("purchase_order_id")

        try:
            purchase_order, summary = import_purchase_order_from_xlsx(
                excel_file=excel_file,
                user=request.user,
                purchase_order_id=purchase_order_id,
            )
        except Exception as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "purchase_order_id": purchase_order.id,
                "summary": summary,
            },
            status=status.HTTP_201_CREATED,
        )


class InventoryDashboardView(APIView):
    permission_classes = [IsAdminOrWorkerUser]

    @staticmethod
    def _product_qs_optimized():
        return Product.objects.select_related(
            "category",
            "product_type_config",
            "single_card__mtg_card",
            "sealed_product",
        ).prefetch_related(
            "bundle_items__item",
            "lots",
        )

    def get(self, request):
        inventory_value_avg_cost = (
            Product.objects.aggregate(
                total=Sum(
                    ExpressionWrapper(
                        F("stock") * F("average_cost_clp"),
                        output_field=IntegerField(),
                    )
                )
            )["total"]
            or 0
        )

        # Dashboard snapshot: fixed short list is intentional for quick rendering.
        out_of_stock = self._product_qs_optimized().filter(stock=0)[:50]

        # Dashboard snapshot: fixed short list is intentional for quick rendering.
        low_stock = self._product_qs_optimized().filter(
            stock__lte=models.F("stock_minimum"),
        ).exclude(
            stock_minimum=0,
        )[:50]

        # Dashboard snapshot: fixed short list is intentional for quick rendering.
        latest_entries = KardexMovement.objects.filter(
            movement_type=KardexMovement.MovementType.PURCHASE_IN,
        )[:10]

        latest_exits = KardexMovement.objects.filter(
            movement_type=KardexMovement.MovementType.SALE_OUT,
        )[:10]

        pending_purchase_orders = PurchaseOrder.objects.filter(
            status__in=[
                PurchaseOrder.Status.DRAFT,
                PurchaseOrder.Status.SENT,
            ],
        ).order_by("-created_at")[:20]

        return Response(
            {
                "inventory_value_avg_cost_clp": inventory_value_avg_cost,
                "products_without_stock": ProductSerializer(
                    out_of_stock,
                    many=True,
                ).data,
                "products_below_minimum_stock": ProductSerializer(
                    low_stock,
                    many=True,
                ).data,
                "latest_entries": KardexMovementSerializer(
                    latest_entries,
                    many=True,
                ).data,
                "latest_exits": KardexMovementSerializer(
                    latest_exits,
                    many=True,
                ).data,
                "purchase_orders_pending_receipt": PurchaseOrderSerializer(
                    pending_purchase_orders,
                    many=True,
                ).data,
            }
        )

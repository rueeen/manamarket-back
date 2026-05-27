from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.dateparse import parse_date

from .models import Category, MTGCard, Product, SingleCard
from .scryfall_normalizer import normalize_card_description
from .services import (
    extract_usd_price,
    get_scryfall_card_by_id,
    resolve_scryfall_card,
)


PREFERRED_SINGLE_CATEGORY_NAMES = {
    "singles",
    "single",
    "cartas individuales",
    "cartas individual",
    "carta individual",
}

PREFERRED_SINGLE_CATEGORY_SLUGS = {"cartas-individuales", "single", "singles", "carta-individual"}


CONDITION_MAP = {
    "NM": Product.CardCondition.NM,
    "EX": Product.CardCondition.LP,
    "LP": Product.CardCondition.LP,
    "VG": Product.CardCondition.MP,
    "MP": Product.CardCondition.MP,
    "HP": Product.CardCondition.HP,
    "DMG": Product.CardCondition.DMG,
}


def normalize_condition(value):
    condition = str(value or "").strip().upper()

    if condition in CONDITION_MAP:
        return CONDITION_MAP[condition]

    raise ValidationError(f"Condición inválida para carta single: {value}")


def resolve_purchase_order_product_category(category=None):
    if category is not None:
        return category

    category = (
        Category.objects.filter(slug__in=PREFERRED_SINGLE_CATEGORY_SLUGS)
        .order_by("name")
        .first()
    )

    if category:
        return category

    categories = list(Category.objects.all().order_by("name"))

    for cat in categories:
        name = str(cat.name or "").strip().lower()

        if name in PREFERRED_SINGLE_CATEGORY_NAMES:
            return cat

    return categories[0] if categories else None


def _has_usable_scryfall_data(item):
    if item.scryfall_id:
        return True

    data = item.scryfall_data or {}

    if not isinstance(data, dict):
        return False

    raw_data = data.get("raw_data")
    if isinstance(raw_data, dict) and raw_data.get("id"):
        return True

    card_data = data.get("card")
    if isinstance(card_data, dict) and card_data.get("id"):
        return True

    if data.get("id") or data.get("scryfall_id"):
        return True

    return False


def _get_clean_card_name_candidates_from_item(item):
    candidates = []

    normalized_name = str(item.normalized_card_name or "").strip()
    raw_description = str(item.raw_description or "").strip()

    if normalized_name:
        candidates.append(normalized_name)

        cleaned_normalized = normalize_card_description(normalized_name).get(
            "normalized_card_name"
        )

        if cleaned_normalized and cleaned_normalized not in candidates:
            candidates.append(cleaned_normalized)

    if raw_description:
        cleaned_raw = normalize_card_description(raw_description).get(
            "normalized_card_name"
        )

        if cleaned_raw and cleaned_raw not in candidates:
            candidates.append(cleaned_raw)

    return candidates


def resolve_purchase_order_item_scryfall(item):
    """
    Garantiza que el PurchaseOrderItem tenga datos suficientes de Scryfall.

    Si el importador solo dejó normalized_card_name/set_name_detected,
    este método busca la carta en Scryfall y guarda scryfall_id/scryfall_data
    en el item para que luego se pueda crear MTGCard/Product/SingleCard.
    """
    if _has_usable_scryfall_data(item):
        return item

    candidate_names = _get_clean_card_name_candidates_from_item(item)

    if not candidate_names:
        raise ValidationError(
            f"Item #{item.id}: no tiene nombre de carta para buscar en Scryfall."
        )

    set_hint = str(getattr(item, "set_name_detected", "") or "").strip()

    is_foil = bool(
        getattr(item, "is_foil_detected", False)
        or getattr(item, "is_foil", False)
        or (item.scryfall_data or {}).get("is_foil_detected", False)
    )

    language = str(
        getattr(item, "language", "")
        or (item.scryfall_data or {}).get("language")
        or "EN"
    ).upper()

    last_error = None
    resolved_name = None
    card_data = None
    warnings = []

    for candidate_name in candidate_names:
        try:
            _card, card_data, warnings = resolve_scryfall_card(
                name=candidate_name)
            resolved_name = candidate_name
            break
        except ValidationError as exc:
            last_error = exc

    if not isinstance(card_data, dict):
        raise ValidationError(
            f"No se pudo resolver Scryfall para item #{item.id}: "
            f"candidatos={candidate_names} / set_hint={set_hint or '-'} "
            f"({last_error})"
        )

    scryfall_id = card_data.get("id") or card_data.get("scryfall_id")

    if not scryfall_id:
        raise ValidationError(
            f"No se pudo resolver Scryfall para item #{item.id}: "
            f"{resolved_name or candidate_names[0]} / set_hint={set_hint or '-'} "
            f"(sin scryfall_id)"
        )

    item.normalized_card_name = resolved_name or item.normalized_card_name
    item.scryfall_id = scryfall_id
    item.scryfall_data = {
        "raw_data": card_data,
        "warnings": warnings or [],
        "set_hint": set_hint,
        "is_foil_detected": is_foil,
        "is_foil_requested": is_foil,
        "language": language,
    }

    update_fields = ["normalized_card_name", "scryfall_id", "scryfall_data"]

    if hasattr(item, "scryfall_status"):
        item.scryfall_status = "matched"
        update_fields.append("scryfall_status")

    item.save(update_fields=update_fields)
    return item


def ensure_item_has_scryfall_data(item):
    return resolve_purchase_order_item_scryfall(item)


def find_existing_single_product(
    *,
    scryfall_id=None,
    mtg_card=None,
    card_name=None,
    condition="NM",
    language="EN",
    is_foil=False,
    set_hint=None,
):
    condition = normalize_condition(condition)
    language = str(language or "EN").strip().upper() or "EN"
    is_foil = bool(is_foil)
    base_qs = SingleCard.objects.select_related("product").filter(
        condition=condition, language=language, is_foil=is_foil
    )

    def _pick(queryset, label):
        matches = list(queryset[:2])
        if len(matches) == 1:
            return matches[0].product, None
        if len(matches) > 1:
            return None, f"múltiples coincidencias en {label}"
        return None, None

    if mtg_card is not None:
        return _pick(base_qs.filter(mtg_card=mtg_card), "mtg_card")
    if scryfall_id:
        product, warning = _pick(base_qs.filter(mtg_card__scryfall_id=scryfall_id), "scryfall_id")
        if product or warning:
            return product, warning
    if card_name:
        product, warning = _pick(base_qs.filter(mtg_card__name__iexact=str(card_name).strip()), "nombre")
        if product or warning:
            return product, warning
        if set_hint:
            set_hint = str(set_hint).strip()
            set_code_hint = set_hint.upper() if 2 <= len(set_hint) <= 6 else ""
            qs = base_qs.filter(mtg_card__name__iexact=str(card_name).strip(), mtg_card__set_name__icontains=set_hint)
            if set_code_hint:
                qs = qs | base_qs.filter(mtg_card__name__iexact=str(card_name).strip(), mtg_card__set_code__iexact=set_code_hint)
            return _pick(qs, "nombre+set")
    return None, None


def find_existing_single_product_for_purchase_item(item):
    """
    Busca un Product single existente para el item sin crear datos nuevos.

    Matching principal:
    - mtg_card.scryfall_id
    - condition
    - language
    - is_foil
    """

    warning_added = False

    def _append_warning(message):
        nonlocal warning_added
        data = item.scryfall_data if isinstance(item.scryfall_data, dict) else {}
        warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []
        warnings.append(message)
        data["warnings"] = warnings
        item.scryfall_data = data
        warning_added = True

    language, is_foil = _get_language_and_foil(item)
    condition = normalize_condition(item.style_condition or Product.CardCondition.NM)

    # 1) scryfall_id ya presente
    product, warning = find_existing_single_product(
        scryfall_id=item.scryfall_id, condition=condition, language=language, is_foil=is_foil
    )
    if product:
        return product
    if warning:
        _append_warning(f"{warning} para item #{item.id}")

    # 2) intentar resolver scryfall y reintentar por scryfall_id
    if not item.scryfall_id:
        try:
            ensure_item_has_scryfall_data(item)
        except ValidationError:
            pass

        if item.scryfall_id:
            product, warning = find_existing_single_product(
                scryfall_id=item.scryfall_id, condition=condition, language=language, is_foil=is_foil
            )
            if product:
                return product
            if warning:
                _append_warning(f"{warning} para item #{item.id}")

    # 3) fallback por nombre exacto (case-insensitive)
    normalized_name = str(item.normalized_card_name or "").strip()
    if normalized_name:
        product, warning = find_existing_single_product(
            card_name=normalized_name,
            set_hint=item.set_name_detected,
            condition=condition,
            language=language,
            is_foil=is_foil,
        )
        if product:
            return product
        if warning:
            _append_warning(f"{warning} para item #{item.id}")

    if warning_added:
        item.save(update_fields=["scryfall_data"])

    return None


def _build_card_payload(item):
    scryfall_data = item.scryfall_data or {}

    if not isinstance(scryfall_data, dict):
        scryfall_data = {}

    raw_data = scryfall_data.get("raw_data")

    if raw_data and isinstance(raw_data, dict):
        return raw_data

    card_data = scryfall_data.get("card")

    if card_data and isinstance(card_data, dict):
        return card_data

    if scryfall_data.get("id"):
        return scryfall_data

    scryfall_id = (
        item.scryfall_id
        or scryfall_data.get("scryfall_id")
        or scryfall_data.get("id")
    )

    if scryfall_id:
        return get_scryfall_card_by_id(scryfall_id)

    raise ValidationError(
        f"El item #{item.id} no tiene datos suficientes de Scryfall. "
        f"raw_description={item.raw_description or '-'}; "
        f"normalized_card_name={item.normalized_card_name or '-'}; "
        f"scryfall_data={scryfall_data or '-'}"
    )


def _get_card_images(card_data):
    image_uris = card_data.get("image_uris") or {}
    card_faces = card_data.get("card_faces") or []

    face_images = {}

    if card_faces and isinstance(card_faces[0], dict):
        face_images = card_faces[0].get("image_uris") or {}

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

    return {
        "image_large": image_large,
        "image_normal": image_normal,
        "image_small": image_small,
    }


def _get_or_update_mtg_card(item, card_data):
    scryfall_id = item.scryfall_id or card_data.get("id")

    if not scryfall_id:
        raise ValidationError("No se pudo obtener scryfall_id para el item.")

    images = _get_card_images(card_data)

    released_at = None

    if card_data.get("released_at"):
        released_at = parse_date(str(card_data.get("released_at")))

    card, _ = MTGCard.objects.update_or_create(
        scryfall_id=scryfall_id,
        defaults={
            "name": card_data.get("name") or item.normalized_card_name,
            "printed_name": card_data.get("printed_name") or "",
            "set_name": card_data.get("set_name") or "",
            "set_code": card_data.get("set") or "",
            "collector_number": card_data.get("collector_number") or "",
            "rarity": card_data.get("rarity") or "",
            "mana_cost": card_data.get("mana_cost") or "",
            "type_line": card_data.get("type_line") or "",
            "oracle_text": card_data.get("oracle_text") or "",
            "colors": card_data.get("colors") or [],
            "color_identity": card_data.get("color_identity") or [],
            "image_large": images["image_large"],
            "image_normal": images["image_normal"],
            "image_small": images["image_small"],
            "scryfall_uri": card_data.get("scryfall_uri") or "",
            "released_at": released_at,
            "raw_data": card_data,
        },
    )

    return card


def _get_language_and_foil(item):
    scryfall_data = item.scryfall_data or {}

    if not isinstance(scryfall_data, dict):
        scryfall_data = {}

    language = str(
        scryfall_data.get("language")
        or getattr(item, "language", "")
        or "EN"
    ).strip().upper() or "EN"

    is_foil = bool(
        scryfall_data.get("is_foil_detected")
        or scryfall_data.get("is_foil_requested")
        or getattr(item, "is_foil_detected", False)
    )

    return language, is_foil


def _build_product_name(card, item, is_foil=False):
    set_code = str(card.set_code or "UNK").upper()
    collector_number = card.collector_number or "?"

    foil_text = " Foil" if is_foil else ""

    return (
        f"{card.name} - {set_code} #{collector_number} "
        f"({item.style_condition}{foil_text})"
    )


def _build_product_description(card):
    parts = []

    if card.type_line:
        parts.append(card.type_line)

    if card.rarity:
        parts.append(f"Rareza: {card.rarity}")

    if card.set_name:
        parts.append(f"Set: {card.set_name}")

    if card.collector_number:
        parts.append(f"Collector #: {card.collector_number}")

    if card.oracle_text:
        parts.append("")
        parts.append(card.oracle_text)

    return "\n".join(parts).strip()


def _get_sale_price(item):
    return int(
        item.sale_price_to_apply_clp
        or item.suggested_sale_price_clp
        or 0
    )


def _get_suggested_price(item):
    return int(item.suggested_sale_price_clp or 0)


@transaction.atomic
def create_product_from_purchase_order_item(item, *, category=None, created_by=None):
    """
    Crea o reutiliza un producto single desde un PurchaseOrderItem.

    Reglas:
    - Si falta Scryfall, intenta resolverlo automáticamente.
    - Usa datos de Scryfall para poblar MTGCard.
    - Evita duplicar SingleCard para la misma carta, condición, idioma y foil.
    - Crea Product inactivo para que el administrador revise antes de publicar.
    - No modifica stock. El stock debe entrar por recepción de orden/lotes/Kardex.
    """
    del created_by

    item = ensure_item_has_scryfall_data(item)

    if not item.scryfall_id and not item.scryfall_data:
        raise ValidationError("El item no tiene scryfall_id ni scryfall_data.")

    if not item.normalized_card_name:
        raise ValidationError("El item no tiene normalized_card_name.")

    if not item.style_condition:
        raise ValidationError("El item no tiene style_condition.")

    item.style_condition = normalize_condition(item.style_condition)

    card_data = _build_card_payload(item)
    card = _get_or_update_mtg_card(item, card_data)

    language, is_foil = _get_language_and_foil(item)

    existing_product, warning = find_existing_single_product(
        mtg_card=card,
        condition=item.style_condition,
        language=language,
        is_foil=is_foil,
    )
    if warning:
        raise ValidationError(f"No se pudo elegir un single existente para item #{item.id}: {warning}.")
    if existing_product:
        item.product = existing_product
        item.save(update_fields=["product"])
        return existing_product, False

    category = resolve_purchase_order_product_category(category)

    product = Product.objects.create(
        name=_build_product_name(card, item, is_foil=is_foil),
        product_type=Product.ProductType.SINGLE,
        category=category,
        price_clp=_get_sale_price(item),
        # Guardamos referencia externa USD (Scryfall/proveedor),
        # no el sugerido CLP calculado localmente.
        price_clp_reference=Decimal(str(extract_usd_price(card_data, is_foil=is_foil) or 0)),
        stock=0,
        image=card.image_large or card.image_normal or card.image_small,
        is_active=False,
        description=_build_product_description(card),
    )

    usd_reference = extract_usd_price(
        card_data,
        is_foil=is_foil,
    )

    SingleCard.objects.create(
        product=product,
        mtg_card=card,
        condition=item.style_condition,
        language=language,
        is_foil=is_foil,
        edition=card.set_name,
        price_usd_reference=Decimal(str(usd_reference or 0)),
    )

    item.product = product
    item.save(update_fields=["product"])

    return product, True

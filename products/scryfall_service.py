import difflib
import time
from decimal import Decimal, InvalidOperation

import requests
from django.core.exceptions import ValidationError


BASE = "https://api.scryfall.com"
TIMEOUT = 12

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "MTG-Ecommerce/1.0",
        "Accept": "application/json",
    }
)


def _first_face_images(data):
    card_faces = data.get("card_faces") or []

    if card_faces and isinstance(card_faces[0], dict):
        return card_faces[0].get("image_uris") or {}

    return {}


def _get_image_uris(data):
    image_uris = data.get("image_uris") or {}

    if image_uris:
        return image_uris

    return _first_face_images(data)


def _build_card_payload(data):
    image_uris = _get_image_uris(data)
    prices = data.get("prices") or {}

    return {
        "scryfall_id": data.get("id", ""),
        "id": data.get("id", ""),
        "name": data.get("name", ""),
        "printed_name": data.get("printed_name", ""),
        "set_name": data.get("set_name", ""),
        "set_code": data.get("set", ""),
        "collector_number": data.get("collector_number", ""),
        "rarity": data.get("rarity", ""),
        "mana_cost": data.get("mana_cost", ""),
        "type_line": data.get("type_line", ""),
        "oracle_text": data.get("oracle_text", ""),
        "colors": data.get("colors") or [],
        "color_identity": data.get("color_identity") or [],
        "released_at": data.get("released_at"),
        "scryfall_uri": data.get("scryfall_uri", ""),
        "image_large": image_uris.get("large", ""),
        "image_normal": image_uris.get("normal", ""),
        "image_small": image_uris.get("small", ""),
        "usd_price": prices.get("usd"),
        "usd_foil_price": prices.get("usd_foil"),
        "usd_etched_price": prices.get("usd_etched"),
        "raw_data": data,
    }


def _get(path, params=None):
    max_attempts = 3
    delay_seconds = 1
    response = None

    for attempt in range(max_attempts):
        try:
            response = SESSION.get(
                f"{BASE}{path}",
                params=params or {},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            return {
                "ok": False,
                "status": None,
                "error": f"Error de red: {exc}",
            }

        # Retry con exponential backoff sólo para 429 y 5xx.
        should_retry = response.status_code == 429 or response.status_code >= 500
        is_last_attempt = attempt == max_attempts - 1

        if should_retry and not is_last_attempt:
            time.sleep(delay_seconds)
            delay_seconds *= 2
            continue

        break

    if response.status_code == 404:
        return {
            "ok": False,
            "status": 404,
            "error": "No encontrado.",
        }

    if response.status_code == 429:
        return {
            "ok": False,
            "status": 429,
            "error": "Scryfall limitó temporalmente las solicitudes.",
        }

    if response.status_code >= 500:
        return {
            "ok": False,
            "status": response.status_code,
            "error": "Scryfall temporalmente no disponible.",
        }

    if response.status_code >= 400:
        return {
            "ok": False,
            "status": response.status_code,
            "error": response.text[:300],
        }

    return {
        "ok": True,
        "data": response.json(),
    }


def _score(card, name, set_hint=None):
    card_name = (card.get("name") or "").lower()
    wanted_name = (name or "").lower()

    name_score = difflib.SequenceMatcher(
        None,
        card_name,
        wanted_name,
    ).ratio()

    if not set_hint:
        return name_score

    card_set_name = (card.get("set_name") or "").lower()
    card_set_code = (card.get("set") or "").lower()
    wanted_set = set_hint.lower()

    set_name_score = difflib.SequenceMatcher(
        None,
        card_set_name,
        wanted_set,
    ).ratio()

    set_code_score = 1 if wanted_set == card_set_code else 0

    return (
        name_score * 0.65
        + max(set_name_score, set_code_score) * 0.35
    )


def _to_decimal(value):
    if value in (None, ""):
        return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


def extract_usd_price(card_data, is_foil=False):
    """
    Extrae precio USD desde payload crudo o payload normalizado.

    Prioridad:
    - Si is_foil=True: usd_foil, usd_etched, usd.
    - Si is_foil=False: usd, usd_foil.
    """
    if not card_data:
        return Decimal("0")

    prices = card_data.get("prices") or {}

    usd = (
        _to_decimal(card_data.get("usd_price"))
        or _to_decimal(prices.get("usd"))
    )

    usd_foil = (
        _to_decimal(card_data.get("usd_foil_price"))
        or _to_decimal(prices.get("usd_foil"))
    )

    usd_etched = (
        _to_decimal(card_data.get("usd_etched_price"))
        or _to_decimal(prices.get("usd_etched"))
    )

    if is_foil:
        return usd_foil or usd_etched or usd or Decimal("0")

    return usd or usd_foil or usd_etched or Decimal("0")


def get_scryfall_card_by_id(scryfall_id):
    if not scryfall_id:
        raise ValidationError("scryfall_id es requerido.")

    result = _get(f"/cards/{scryfall_id}")

    if not result.get("ok"):
        raise ValidationError(result.get(
            "error") or "No se pudo obtener la carta desde Scryfall.")

    return result["data"]


def search_scryfall_card(card_name, set_hint=None, is_foil=False):
    if not card_name:
        return {
            "found": False,
            "status": "error",
            "message": "card_name es requerido.",
            "suggestions": [],
        }

    for mode, params in (
        ("exact", {"exact": card_name}),
        ("fuzzy", {"fuzzy": card_name}),
    ):
        result = _get("/cards/named", params)

        if result.get("ok"):
            payload = _build_card_payload(result["data"])
            payload.update(
                {
                    "found": True,
                    "status": "matched",
                    "match_mode": mode,
                    "suggestions": [],
                    "is_foil_requested": is_foil,
                }
            )
            return payload

        if result.get("status") not in (404, None):
            return {
                "found": False,
                "status": "error",
                "message": result.get("error"),
                "suggestions": [],
            }

    query = f'!"{card_name}"'

    if set_hint:
        cleaned_set_hint = str(set_hint).strip()

        if len(cleaned_set_hint) <= 5:
            query = f'{query} set:{cleaned_set_hint.lower()}'

    result = _get("/cards/search", {"q": query})

    if not result.get("ok"):
        fallback_result = _get("/cards/search", {"q": card_name})

        if not fallback_result.get("ok"):
            if result.get("status") == 404:
                return {
                    "found": False,
                    "status": "not_found",
                    "message": "Carta no encontrada.",
                    "suggestions": [],
                }

            return {
                "found": False,
                "status": "error",
                "message": result.get("error"),
                "suggestions": [],
            }

        result = fallback_result

    cards = result["data"].get("data", [])

    if not cards:
        return {
            "found": False,
            "status": "not_found",
            "message": "Carta no encontrada.",
            "suggestions": [],
        }

    ranked = sorted(
        cards,
        key=lambda card: _score(card, card_name, set_hint),
        reverse=True,
    )

    top = ranked[0]

    suggestions = [
        {
            "name": card.get("name"),
            "set_name": card.get("set_name"),
            "set_code": card.get("set"),
            "collector_number": card.get("collector_number"),
            "scryfall_id": card.get("id"),
        }
        for card in ranked[1:4]
    ]

    payload = _build_card_payload(top)
    payload.update(
        {
            "found": True,
            "status": "matched",
            "match_mode": "search",
            "suggestions": suggestions,
            "is_foil_requested": is_foil,
        }
    )

    return payload

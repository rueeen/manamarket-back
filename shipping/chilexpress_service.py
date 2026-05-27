import json
import logging
import urllib.error
import urllib.request

import requests
from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

# Mapeo de nombre de región (del JSON local) a código de región de Chilexpress
_REGION_CODES = {
    # clave: nombre normalizado (sin tildes, minusculas) -> regionId real de la API Chilexpress
    'tarapaca': 'R1',
    'antofagasta': 'R2',
    'atacama': 'R3',
    'coquimbo': 'R4',
    'valparaiso': 'R5',
    'libertador gral bernardo o higgins': 'R6',
    "libertador general bernardo o'higgins": 'R6',
    'libertador general bernardo ohiggins': 'R6',
    "o'higgins": 'R6',
    'maule': 'R7',
    'biobio': 'R8',
    'araucania': 'R9',
    'la araucania': 'R9',
    'metropolitana de santiago': 'RM',
    'metropolitana': 'RM',
    'rm': 'RM',
    'los lagos': 'R10',
    'aisen del gral c ibanez del campo': 'R11',
    'aysen': 'R11',
    'magallanes y la antartica chilena': 'R12',
    'magallanes': 'R12',
    'los rios': 'R14',
    'arica y parinacota': 'R15',
    'nuble': 'R16',
}


def _env():
    return getattr(settings, 'CHILEXPRESS_ENV', 'test')


def _coverage_base():
    return (
        'https://testservices.wschilexpress.com/georeference/api/v1.0'
        if _env() == 'test'
        else 'https://services.wschilexpress.com/georeference/api/v1.0'
    )


def _rating_base():
    return (
        'https://testservices.wschilexpress.com/rating/api/v1.0'
        if _env() == 'test'
        else 'https://services.wschilexpress.com/rating/api/v1.0'
    )


def _chilexpress_get(url, api_key):
    req = urllib.request.Request(
        url,
        headers={
            'Cache-Control': 'no-cache',
            'Ocp-Apim-Subscription-Key': api_key,
        },
        method='GET',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore') if hasattr(exc, 'read') else ''
        raise ValidationError(
            f'Chilexpress Coverage devolvió {exc.code}: {body[:200]}'
        ) from exc
    except urllib.error.URLError as exc:
        raise ValidationError(
            f'No fue posible conectar con Chilexpress: {exc.reason}'
        ) from exc


def _chilexpress_post(url, api_key, payload):
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'Cache-Control': 'no-cache',
            'Ocp-Apim-Subscription-Key': api_key,
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body_txt = exc.read().decode('utf-8', errors='ignore') if hasattr(exc, 'read') else ''
        raise ValidationError(
            f'Chilexpress Rating devolvió {exc.code}: {body_txt[:200]}'
        ) from exc
    except urllib.error.URLError as exc:
        raise ValidationError(
            f'No fue posible conectar con Chilexpress: {exc.reason}'
        ) from exc


def _get_communes_for_region(api_key, region_code):
    """Obtiene áreas de cobertura de una región específica de Chilexpress."""
    url = f'{_coverage_base()}/coverage-areas?RegionCode={region_code}&type=0'
    try:
        data = _chilexpress_get(url, api_key)
        areas = data.get('coverageAreas', [])
        if areas:
            logger.debug(
                'Región %s: %d áreas. Keys del primer item: %s. Ejemplo: %s',
                region_code,
                len(areas),
                list(areas[0].keys()),
                areas[0],
            )
        else:
            logger.debug(
                'Región %s: 0 áreas. Response keys: %s',
                region_code,
                list(data.keys()),
            )
        return areas
    except ValidationError as exc:
        logger.warning('Coverage error región %s: %s', region_code, exc)
        return []


def _normalize(text):
    """Normaliza texto para comparación: minúsculas y sin tildes."""
    import unicodedata

    text = text.strip().lower()
    return ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )


def get_coverage_code(commune_name, region_name=None):
    api_key = getattr(settings, 'CHILEXPRESS_COVERAGE_KEY', '')
    if not api_key:
        logger.warning('CHILEXPRESS_COVERAGE_KEY no configurada')
        return None

    commune_norm = _normalize(commune_name)

    region_codes_to_try = []
    if region_name:
        code = _REGION_CODES.get(_normalize(region_name))
        if code:
            region_codes_to_try = [code]

    if not region_codes_to_try:
        region_codes_to_try = list(dict.fromkeys(_REGION_CODES.values()))  # sin duplicados

    for region_code in region_codes_to_try:
        areas = _get_communes_for_region(api_key, region_code)
        for area in areas:
            # Buscar por coverageName (sector exacto) o countyName (agrupación)
            coverage = area.get('coverageName') or ''
            county = area.get('countyName') or ''
            if _normalize(coverage) == commune_norm or _normalize(county) == commune_norm:
                code = area.get('countyCode') or area.get('coverageCode') or ''
                logger.info(
                    'Cobertura encontrada: %s -> %s (coverageName=%s, region %s)',
                    commune_name, code, coverage, region_code
                )
                return code

    logger.warning('Sin cobertura Chilexpress para: %s', commune_name)
    return None


def quote_shipment(
    commune_name,
    region_name=None,
    weight_kg=0.5,
    length_cm=20,
    width_cm=15,
    height_cm=10,
    declared_worth=0,
):
    cotizador_key = getattr(settings, 'CHILEXPRESS_COTIZADOR_KEY', '')
    origin = getattr(settings, 'CHILEXPRESS_ORIGEN_COVERAGE', 'STGO')

    if not cotizador_key:
        logger.warning('CHILEXPRESS_COTIZADOR_KEY no configurada')
        return None

    dest_code = get_coverage_code(commune_name, region_name=region_name)
    if not dest_code:
        return None

    # Peso volumétrico: largo * ancho * alto / 4000 (estándar courier)
    volumetric = (length_cm * width_cm * height_cm) / 4000
    effective_weight = max(float(weight_kg), volumetric)

    payload = {
        'originCountyCode': origin,
        'destinationCountyCode': dest_code,
        'package': {
            'weight': f'{effective_weight:.2f}',
            'height': f'{float(height_cm):.2f}',
            'width': f'{float(width_cm):.2f}',
            'length': f'{float(length_cm):.2f}',
        },
        'productType': 3,  # Sobre/paquete estándar
        'contentType': 1,  # Mercadería
        'declaredWorth': str(int(declared_worth)),
        'deliveryTime': 0,  # Sin preferencia
    }

    try:
        data = _chilexpress_post(
            f'{_rating_base()}/rates/courier',
            cotizador_key,
            payload,
        )
    except ValidationError as exc:
        logger.warning('Rating error para %s: %s', commune_name, exc)
        return None

    # La API devuelve courierServiceOptions (no courierServiceRates)
    rates = data.get('data', {}).get('courierServiceOptions', [])
    if not rates:
        logger.warning(
            'Chilexpress no devolvió opciones para %s. Response: %s',
            commune_name, data
        )
        return None

    # Elegir la opción más barata con deliveryType=0 (domicilio), si existe
    home_delivery = [r for r in rates if r.get('deliveryType') == 0]
    candidates = home_delivery if home_delivery else rates
    best = min(candidates, key=lambda r: float(r.get('serviceValue', 9_999_999)))

    return {
        'amount': int(float(best.get('serviceValue', 0))),
        'service_name': best.get('serviceDescription', 'Chilexpress'),
        'service_type_code': best.get('serviceTypeCode'),
        'delivery_time': best.get('deliveryTime', ''),
        'final_weight': best.get('finalWeight', ''),
        'used_volumetric': best.get('didUseVolumetricWeight', False),
    }


# ── Función existente — NO MODIFICAR ──────────────────────────────────────

def create_shipment(order):
    env = getattr(settings, "CHILEXPRESS_ENV", "test")
    if env == "test":
        return {
            "tracking_number": f"TEST-{order.id}",
            "label_url": f"https://test.chilexpress.cl/labels/{order.id}.pdf",
            "status": "created",
        }

    api_key = getattr(settings, "CHILEXPRESS_ENVIOS_KEY", "")
    tcc = getattr(settings, "CHILEXPRESS_TCC", "")

    if not api_key or not tcc:
        raise ValidationError("Faltan credenciales de Chilexpress (CHILEXPRESS_ENVIOS_KEY/CHILEXPRESS_TCC).")

    endpoint = getattr(
        settings,
        "CHILEXPRESS_ENVIOS_URL",
        "https://api.chilexpress.cl/transport-orders/api/v1.0/transport-orders",
    )

    payload = {
        "reference": str(order.id),
        "tcc": tcc,
        "recipient": {
            "name": getattr(order, "recipient_name", "") or order.user.get_full_name() or order.user.username,
            "email": order.user.email,
            "phone": getattr(order, "recipient_phone", ""),
        },
        "delivery": {
            "street_name": getattr(order, "shipping_street", ""),
            "street_number": getattr(order, "shipping_number", ""),
            "commune_name": getattr(order, "shipping_commune", ""),
            "region_id": getattr(order, "shipping_region", ""),
            "notes": getattr(order, "shipping_notes", ""),
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Ocp-Apim-Subscription-Key": api_key,
    }

    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise ValidationError(f"Error al conectar con Chilexpress: {exc}") from exc

    if response.status_code >= 400:
        raise ValidationError(f"Chilexpress devolvió error {response.status_code}: {response.text}")

    data = response.json()
    tracking_number = (
        data.get("tracking_number")
        or data.get("trackingNumber")
        or data.get("numero_tracking")
        or ""
    )
    label_url = data.get("label_url") or data.get("labelUrl") or data.get("etiqueta") or ""

    if not tracking_number:
        raise ValidationError("Chilexpress no devolvió tracking_number.")

    return {
        "tracking_number": tracking_number,
        "label_url": label_url,
        "raw_response": data,
    }

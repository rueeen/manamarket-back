import re


REMOVE_TOKENS = [
    "Variants",
    "Variant",
    "Commander Decks",
    "Commander Deck",
    "Eternal-Legal",
    "Showcase",
    "Showcas",
    "Extended Art",
    "Extend",
    "Borderless",
    "Retro Frame",
    "Alternate Art",
    "Etched",
    "Surge Foil",
    "Traditional Foil",
    "Foil",
]


FOIL_TOKENS = [
    "foil",
    "surge foil",
    "traditional foil",
    "etched foil",
]


TREATMENT_TOKENS = [
    "Showcase",
    "Showcas",
    "Extended Art",
    "Extend",
    "Borderless",
    "Retro Frame",
    "Alternate Art",
    "Etched",
    "Surge Foil",
    "Traditional Foil",
]


def _clean_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" -:")


def _contains_token(text: str, token: str) -> bool:
    return bool(
        re.search(
            rf"\b{re.escape(token)}\b",
            text or "",
            flags=re.IGNORECASE,
        )
    )


def _detect_foil(raw: str) -> bool:
    text = raw or ""

    return any(
        _contains_token(text, token)
        for token in FOIL_TOKENS
    )


def _detect_treatment(raw: str) -> str:
    detected = []

    for token in TREATMENT_TOKENS:
        if _contains_token(raw, token):
            detected.append(token)

    return ", ".join(detected)


def _remove_tokens(text: str) -> str:
    cleaned = text or ""

    for token in REMOVE_TOKENS:
        cleaned = re.sub(
            rf"\b{re.escape(token)}\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

    return _clean_spaces(cleaned)


def _remove_parenthetical_noise(text: str) -> str:
    cleaned = text or ""

    # Elimina paréntesis completos: "(Extended Art)", "(Foil)", "(0329 - Showcase)"
    cleaned = re.sub(r"\([^)]*\)", "", cleaned)

    # Elimina paréntesis incompletos/truncados al final:
    # "(Extend", "(0329 - Showcas", "(Borderless"
    cleaned = re.sub(r"\([^)]*$", "", cleaned)

    return _clean_spaces(cleaned)


def normalize_card_description(raw_description: str) -> dict:
    raw = (raw_description or "").strip()
    warnings = []

    is_foil = _detect_foil(raw)
    treatment = _detect_treatment(raw)

    set_name = ""
    card_name = raw

    if ":" in raw:
        left, right = raw.rsplit(":", 1)
        set_name = _clean_spaces(_remove_tokens(left))
        card_name = right

    # Algunos listados traen puntos suspensivos o unicode ellipsis.
    card_name = card_name.replace("...", " ")
    card_name = card_name.replace("…", " ")

    card_name = _remove_parenthetical_noise(card_name)
    card_name = _remove_tokens(card_name)
    card_name = _clean_spaces(card_name)

    if not card_name:
        warnings.append("No se pudo normalizar el nombre de carta.")

    return {
        "raw_description": raw,
        "normalized_card_name": card_name,
        "set_name_detected": set_name,
        "is_foil_detected": is_foil,
        "treatment_detected": treatment,
        "warnings": warnings,
    }

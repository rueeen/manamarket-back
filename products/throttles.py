from rest_framework.throttling import UserRateThrottle


class ScryfallThrottle(UserRateThrottle):
    scope = "scryfall"

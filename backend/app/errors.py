class ProviderError(Exception):
    """Upstream weather/geocoding API failed or returned something unusable."""


class DataQualityError(Exception):
    """Data was fetched but is not good enough to analyse."""


class StorageError(Exception):
    """Database unavailable or failed."""

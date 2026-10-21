"""Errors the services raise; the API layer turns them into HTTP responses."""


class NotFound(Exception):
    """A trip or route that doesn't exist. The message is what the client is told ("Trip not found")."""

"""Custom exceptions for save parsing and mapping."""


class SaveParseError(Exception):
    """Base error for save parsing failures."""


class UnsupportedSaveFormatError(SaveParseError):
    """Raised when the input is not a supported save representation."""


class UnsupportedTopLevelRecordError(SaveParseError):
    """Raised when a top-level member uses an unexpected record shape."""


class FieldDecodeError(SaveParseError):
    """Raised when a field cannot be normalized into the snapshot model."""

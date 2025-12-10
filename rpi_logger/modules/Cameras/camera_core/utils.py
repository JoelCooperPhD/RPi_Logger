"""Utility functions for camera_core module."""


def to_snake_case(name: str) -> str:
    """Convert PascalCase to snake_case.

    Used primarily for converting camera control names to v4l2 format.

    Examples:
        >>> to_snake_case("Brightness")
        'brightness'
        >>> to_snake_case("AutoExposure")
        'auto_exposure'
        >>> to_snake_case("WhiteBalanceBlueU")
        'white_balance_blue_u'
    """
    result = []
    for i, char in enumerate(name):
        if i > 0 and char.isupper():
            result.append("_")
        result.append(char.lower())
    return "".join(result)

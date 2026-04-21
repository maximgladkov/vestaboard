"""Vestaboard character code map and text-to-codes helper.

Reference: https://docs.vestaboard.com/docs/characterCodes
"""

from __future__ import annotations

BLANK = 0

CHAR_CODES: dict[str, int] = {
    " ": 0,
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8, "I": 9,
    "J": 10, "K": 11, "L": 12, "M": 13, "N": 14, "O": 15, "P": 16, "Q": 17,
    "R": 18, "S": 19, "T": 20, "U": 21, "V": 22, "W": 23, "X": 24, "Y": 25,
    "Z": 26,
    "1": 27, "2": 28, "3": 29, "4": 30, "5": 31, "6": 32, "7": 33, "8": 34,
    "9": 35, "0": 36,
    "!": 37,
    "@": 38,
    "#": 39,
    "$": 40,
    "(": 41,
    ")": 42,
    "-": 44,
    "+": 46,
    "&": 47,
    "=": 48,
    ";": 49,
    ":": 50,
    "'": 52,
    '"': 53,
    "%": 54,
    ",": 55,
    ".": 56,
    "/": 59,
    "?": 60,
}


def text_to_codes(text: str) -> list[int]:
    """Convert a string to a list of Vestaboard character codes.

    Uppercases the input and replaces unsupported characters with blanks so
    the board never rejects the message.
    """
    codes: list[int] = []
    for ch in text.upper():
        codes.append(CHAR_CODES.get(ch, BLANK))
    return codes


def sanitize(text: str) -> str:
    """Return the input with unsupported characters replaced by spaces.

    Useful when we still need string-level truncation before layout.
    """
    return "".join(ch if ch.upper() in CHAR_CODES else " " for ch in text.upper())

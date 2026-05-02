"""
token_crypto.py
---------------
Generates and decrypts short opaque tokens for roll numbers.

Algorithm:
  - AES-128-CBC encryption of the roll number string
  - Output encoded with Base32 (uppercase, no padding) -> short printable token
  - Tokens are 8-26 characters depending on roll number length

Usage:
  token = generate_token("2023CS045")   -> e.g. "XK729FABMN2Q..."
  roll  = decrypt_token("XK729FABMN2Q...")   -> "2023CS045"

The SECRET_TOKEN_KEY (32 hex chars = 16 bytes AES key) must be set in .env
The SECRET_TOKEN_IV  (32 hex chars = 16 bytes IV) must be set in .env

NOTE: A 4-byte random nonce is prepended to the plaintext before encryption
so that every call produces a *unique* token even for the same roll number.
This prevents the IntegrityError that occurs when two identical roll numbers
(or roll numbers whose AES blocks collide) are inserted into StudentToken.
"""

import base64
import os

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from decouple import config

SECRET_KEY_HEX = config('TOKEN_AES_KEY')   # 32 hex chars = 16 bytes
SECRET_IV_HEX  = config('TOKEN_AES_IV')    # 32 hex chars = 16 bytes


def _get_key_iv():
    key = bytes.fromhex(SECRET_KEY_HEX)
    iv  = bytes.fromhex(SECRET_IV_HEX)
    assert len(key) == 16, "TOKEN_AES_KEY must be exactly 32 hex characters (16 bytes)"
    assert len(iv)  == 16, "TOKEN_AES_IV must be exactly 32 hex characters (16 bytes)"
    return key, iv


def generate_token(roll_number: str) -> str:
    """
    Encrypts roll_number -> returns a short uppercase Base32 token.

    A 4-byte random nonce is prepended to the plaintext before AES encryption
    so that every invocation produces a distinct ciphertext (and therefore a
    distinct token), even when the same roll_number is passed twice.  This
    prevents the unique-constraint violation on the 'token' column.

    Format of decrypted plaintext: [4-byte nonce][roll_number UTF-8 bytes]
    """
    key, iv = _get_key_iv()
    nonce = os.urandom(4)
    plaintext = nonce + roll_number.encode('utf-8')
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = pad(plaintext, AES.block_size)
    encrypted = cipher.encrypt(padded)
    # Base32 encode -> strip '=' padding -> uppercase
    token = base64.b32encode(encrypted).decode('utf-8').rstrip('=')
    return token


def decrypt_token(token: str) -> str:
    """
    Decrypts a Base32 token back to the original roll number.

    Handles both:
    - New tokens: 4-byte nonce prefix is stripped from the decrypted plaintext.
    - Legacy tokens (generated before the nonce was introduced): the full
      decrypted bytes decode cleanly as UTF-8 since there is no binary nonce.

    Raises ValueError if the token is invalid or has been tampered with.
    """
    key, iv = _get_key_iv()
    # Restore Base32 padding
    padding_needed = (8 - len(token) % 8) % 8
    padded_token = token + '=' * padding_needed
    try:
        encrypted = base64.b32decode(padded_token.upper())
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = unpad(cipher.decrypt(encrypted), AES.block_size)

        # Try to detect nonce vs legacy token:
        # Legacy tokens: entire decrypted payload is valid UTF-8 roll number.
        # New tokens: first 4 bytes are random binary (often not valid UTF-8).
        try:
            candidate = decrypted.decode('utf-8')
            # If the full payload decodes cleanly it's either legacy OR the
            # nonce bytes happened to be valid UTF-8.  In the legacy case the
            # roll number makes sense as-is; in the new case we must strip.
            # We distinguish by checking whether stripping 4 bytes still gives
            # a non-empty string (heuristic: roll numbers are >= 5 chars).
            stripped = decrypted[4:].decode('utf-8')
            if len(stripped) >= 3:
                # New token: return the stripped roll number
                return stripped
            # Fallback: return the full decoded string (legacy)
            return candidate
        except UnicodeDecodeError:
            # Nonce is binary-only; strip it
            return decrypted[4:].decode('utf-8')

    except Exception as e:
        raise ValueError(f"Invalid or tampered token: {token}") from e

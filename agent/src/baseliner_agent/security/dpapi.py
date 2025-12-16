from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

# DPAPI flags
CRYPTPROTECT_UI_FORBIDDEN = 0x01
CRYPTPROTECT_LOCAL_MACHINE = 0x04

_IS_WINDOWS = os.name == "nt"
crypt32 = None
kernel32 = None

if _IS_WINDOWS:
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:
        _IS_WINDOWS = False
        crypt32 = None
        kernel32 = None


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _raise_last_winerror(msg: str) -> None:
    err = ctypes.get_last_error()
    raise OSError(err, f"{msg} (winerror={err})")


if _IS_WINDOWS and crypt32 and kernel32:
    # BOOL CryptProtectData(
    #   DATA_BLOB* pDataIn,
    #   LPCWSTR szDataDescr,
    #   DATA_BLOB* pOptionalEntropy,
    #   PVOID pvReserved,
    #   CRYPTPROTECT_PROMPTSTRUCT* pPromptStruct,
    #   DWORD dwFlags,
    #   DATA_BLOB* pDataOut
    # );
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL

    # BOOL CryptUnprotectData(
    #   DATA_BLOB* pDataIn,
    #   LPWSTR* ppszDataDescr,
    #   DATA_BLOB* pOptionalEntropy,
    #   PVOID pvReserved,
    #   CRYPTPROTECT_PROMPTSTRUCT* pPromptStruct,
    #   DWORD dwFlags,
    #   DATA_BLOB* pDataOut
    # );
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL

    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p


if not _IS_WINDOWS or not crypt32 or not kernel32:

    def protect_bytes(data: bytes, *, local_machine: bool = True) -> bytes:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("protect_bytes expects bytes")
        # Non-Windows fallback: store plaintext for dev/test convenience.
        return bytes(data)

    def unprotect_bytes(data: bytes) -> bytes:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("unprotect_bytes expects bytes")
        return bytes(data)

else:

    def protect_bytes(data: bytes, *, local_machine: bool = True) -> bytes:
        """
        Protect bytes using DPAPI.

        local_machine=True => token can be unprotected by any account on the same machine
                             (good for scheduled tasks as SYSTEM vs CURRENTUSER).
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("protect_bytes expects bytes")

        flags = CRYPTPROTECT_UI_FORBIDDEN
        if local_machine:
            flags |= CRYPTPROTECT_LOCAL_MACHINE

        in_buf = ctypes.create_string_buffer(bytes(data), len(data))
        in_blob = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_byte)))

        out_blob = DATA_BLOB()
        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(out_blob),
        )
        if not ok:
            _raise_last_winerror("CryptProtectData failed")

        try:
            protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return protected
        finally:
            if out_blob.pbData:
                kernel32.LocalFree(out_blob.pbData)

    def unprotect_bytes(data: bytes) -> bytes:
        """
        Unprotect bytes using DPAPI.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("unprotect_bytes expects bytes")

        in_buf = ctypes.create_string_buffer(bytes(data), len(data))
        in_blob = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_byte)))

        out_blob = DATA_BLOB()
        desc = wintypes.LPWSTR()

        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            ctypes.byref(desc),
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            _raise_last_winerror("CryptUnprotectData failed")

        try:
            plain = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return plain
        finally:
            if out_blob.pbData:
                kernel32.LocalFree(out_blob.pbData)
            if desc:
                kernel32.LocalFree(desc)

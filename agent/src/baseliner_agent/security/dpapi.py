"""
Minimal DPAPI wrapper via ctypes (Windows only).

NOTE: This uses Current User protection by default.
For a future service, consider switching to LocalMachine scope or running under a fixed service account.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

CRYPTPROTECT_UI_FORBIDDEN = 0x01


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CryptProtectData = crypt32.CryptProtectData
CryptProtectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    wintypes.LPCWSTR,
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
CryptProtectData.restype = wintypes.BOOL

CryptUnprotectData = crypt32.CryptUnprotectData
CryptUnprotectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
CryptUnprotectData.restype = wintypes.BOOL

LocalFree = kernel32.LocalFree
LocalFree.argtypes = [ctypes.c_void_p]
LocalFree.restype = ctypes.c_void_p


def _blob_from_bytes(data: bytes) -> DATA_BLOB:
    buf = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    return DATA_BLOB(cbData=len(data), pbData=ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))


def _bytes_from_blob(blob: DATA_BLOB) -> bytes:
    if blob.cbData == 0:
        return b""
    ptr = ctypes.cast(blob.pbData, ctypes.POINTER(ctypes.c_byte))
    return bytes(bytearray(ptr[: blob.cbData]))


def dpapi_encrypt(data: bytes) -> bytes:
    in_blob = _blob_from_bytes(data)
    out_blob = DATA_BLOB()
    ok = CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return _bytes_from_blob(out_blob)
    finally:
        LocalFree(out_blob.pbData)


def dpapi_decrypt(data: bytes) -> bytes:
    in_blob = _blob_from_bytes(data)
    out_blob = DATA_BLOB()
    ppsz_desc = wintypes.LPWSTR()
    ok = CryptUnprotectData(
        ctypes.byref(in_blob),
        ctypes.byref(ppsz_desc),
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return _bytes_from_blob(out_blob)
    finally:
        if ppsz_desc:
            LocalFree(ppsz_desc)
        LocalFree(out_blob.pbData)

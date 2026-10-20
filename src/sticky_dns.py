"""Cache DNS answers per process, and reuse the last good one when a lookup fails.

The campus DNS this Mac uses fails now and then ("nodename nor servname provided" on 2026-10-20 while the
network was up) and sometimes hangs: requests' timeouts don't cover name resolution, so one Open-Meteo call
took 149 s despite a 60 s deadline. Importing this module patches socket.getaddrinfo for the process:
- an answer younger than TTL_S is reused without a lookup (no hang, no failure);
- an older one is refreshed, and if that lookup fails the stale answer is returned instead of raising;
- a host never resolved before still raises.
"""
from __future__ import annotations

import socket
import time

TTL_S = 1800
_getaddrinfo = socket.getaddrinfo
_cache: dict = {}  # key -> (resolved_at, result)


def getaddrinfo_sticky(host, *args, **kw):
    key = (host, args, tuple(sorted(kw.items())))
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL_S:
        return hit[1]
    try:
        res = _getaddrinfo(host, *args, **kw)
    except socket.gaierror:
        if hit:
            return hit[1]
        raise
    _cache[key] = (time.monotonic(), res)
    return res


if socket.getaddrinfo is not getaddrinfo_sticky:
    socket.getaddrinfo = getaddrinfo_sticky

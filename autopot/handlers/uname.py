# python
"""
autopot/handlers/uname.py
Handler for `uname` command returning plausible uname -a string.
"""
import platform
import datetime


async def run(session, argv):
    """
    Return a plausible `uname -a` string.
    """
    sys = "Linux"
    nodename = session.username or "honeypot"
    release = platform.release() or "5.4.0"
    version = platform.version() or "#1 SMP Thu Jan  1 00:00:00 UTC 1970"
    machine = platform.machine() or "x86_64"
    out = f"{sys} {nodename} {release} {version} {machine}"
    return out

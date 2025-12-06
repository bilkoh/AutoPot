# python
"""
autopot/handlers/whoami.py
Handler for `whoami` command that reports the session username.
"""


async def run(session, argv):
    user_label = session.username or "guest"
    return user_label

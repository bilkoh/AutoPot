# python
"""
autopot/handlers/id.py
Handler for `id` command that uses the authenticated username to build the response.
"""


async def run(session, argv):
    user_label = session.username or "root"
    return f"uid=1000({user_label}) gid=1000({user_label}) groups=1000({user_label})"

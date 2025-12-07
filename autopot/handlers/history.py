# python
"""
autopot/handlers/history.py
Handler for the `history` command that echoes the stored session history.
"""


async def run(session, argv):
    """
    Return the recorded session commands, one per line.
    """
    return "\n".join(session.history)

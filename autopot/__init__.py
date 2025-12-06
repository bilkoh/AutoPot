# python
"""autopot package"""
__version__ = "0.1"

from autopot.env import load_env

# Load .env values at import time so clients rely on python-dotenv instead of manual parsing.
load_env()

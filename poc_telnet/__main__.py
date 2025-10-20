# python
"""
poc_telnet.__main__
Entry point for python -m poc_telnet
"""
import asyncio, argparse
from . import start as start_server

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2323)
    args = parser.parse_args()
    try:
        asyncio.run(start_server(host=args.host, port=args.port))
    except KeyboardInterrupt:
        print("shutting down")

if __name__ == "__main__":
    main()
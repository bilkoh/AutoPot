# python
"""
poc_telnet/__init__.py
Minimal POC telnet server using telnetlib3.

Usage:
    python -m poc_telnet --port 2323

This is a standalone package (module) that demonstrates a minimal telnetlib3
server which sends a banner and echoes received lines. It intentionally does
NOT perform any authentication or command execution — it's a pure I/O POC.
"""
import asyncio
import argparse
import telnetlib3

BANNER = "POC Telnet Server"

async def shell(reader, writer):
    peer = writer.get_extra_info("peername") or ("0.0.0.0", 0)
    print(f"connection from {peer}")
    try:
        # Send banner
        writer.write(BANNER + "\r\n")
        await writer.drain()

        # Echo loop
        while True:
            line = await reader.readline()
            # telnetlib3 returns None on EOF/closed connection
            if line is None:
                break
            line = line.rstrip("\r\n")
            if not line:
                continue
            writer.write(f"You said: {line}\r\n")
            await writer.drain()
    except Exception as exc:
        print("shell exception:", exc)
    finally:
        try:
            writer.close()
        except Exception:
            pass
        print("connection closed", peer)

async def start(host: str = "127.0.0.1", port: int = 2323):
    server = await telnetlib3.create_server(shell=shell, host=host, port=port)
    print(f"Listening on {host}:{port}")
    # Keep the server running until cancelled
    await asyncio.Event().wait()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=2323, type=int)
    args = parser.parse_args()
    try:
        asyncio.run(start(host=args.host, port=args.port))
    except KeyboardInterrupt:
        print("shutting down")
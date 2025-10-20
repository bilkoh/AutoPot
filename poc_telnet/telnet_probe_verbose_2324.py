# python
"""
scripts/telnet_probe_verbose.py
Connects to the local telnet honeypot and prints raw negotiation + payload bytes.
Run from repo root:
    python scripts/telnet_probe_verbose.py
"""
import socket
import time
import binascii

HOST = "127.0.0.1"
PORT = 2324
RECV_TIMEOUT = 2.0
MAX_ITER = 50


def hexdump(b: bytes) -> str:
    return binascii.hexlify(b).decode("ascii")


def main():
    addr = (HOST, PORT)
    print(f"connecting to {addr!r}")
    s = socket.create_connection(addr, timeout=5)
    s.settimeout(RECV_TIMEOUT)
    try:
        i = 0
        while i < MAX_ITER:
            try:
                data = s.recv(4096)
            except socket.timeout:
                print("recv timeout (no data for now)")
                break
            if data == b"":
                print("socket closed by peer (recv returned empty)")
                return
            print(f"[RECV {i}] {len(data)} bytes")
            print("  raw:", data)
            print("  hex:", hexdump(data))
            i += 1
            # small pause to allow negotiation frames to arrive
            time.sleep(0.05)
        # send a newline to trigger auth prompt handling
        print("sending newline to probe auth prompt")
        s.sendall(b"\r\n")
        try:
            data = s.recv(4096)
            if data == b"":
                print("socket closed by peer after send (recv empty)")
            else:
                print("[AFTER SEND] received:")
                print("  raw:", data)
                print("  hex:", hexdump(data))
        except socket.timeout:
            print("no response after send (timed out)")
        # keep connection open and read more to see if server closes later
        print("waiting 10s to observe any disconnects")
        end = time.time() + 10
        while time.time() < end:
            try:
                data = s.recv(4096)
            except socket.timeout:
                # no data, continue waiting
                continue
            if data == b"":
                print("socket closed by peer during idle wait")
                return
            print("[IDLE RECV] bytes:", len(data))
    finally:
        try:
            s.close()
        except Exception:
            pass
    print("probe finished")


if __name__ == "__main__":
    main()

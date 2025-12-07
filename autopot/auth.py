# python
"""
autopot/auth.py
Simple AuthGate: prompt for login and password, log attempts, accept all creds (stub).
"""
import asyncio
import pathlib
from typing import Optional
from .session import Session


class AuthGate:
    def __init__(
        self,
        session: Session,
        userdb_path: pathlib.Path,
        max_attempts: int = 3,
        fail_delay: float = 2.0,
    ):
        self.session = session
        self.userdb_path = pathlib.Path(userdb_path)
        self.max_attempts = max_attempts
        self.fail_delay = fail_delay

    async def run(self, reader, writer) -> bool:
        """
        Run login loop with additional debug logging to diagnose early disconnects.

        Notes:
        - We log entry/exit and every significant step to events.jsonl so that a
          quick connect->close sequence can be diagnosed.
        - We treat both None and empty string as EOF/disconnect, but log the raw
          value received to make behavior obvious.
        """
        await self.session.log("auth.start", "auth")
        attempts = 0
        READ_TIMEOUT = 60.0

        try:
            while attempts < self.max_attempts:
                await self.session.log(
                    "auth.step", "auth", step="prompt_username", attempt=attempts
                )
                # prompt for username
                try:
                    writer.write("\r\nlogin: ")
                    await writer.drain()
                except Exception as e:
                    await self.session.log(
                        "auth.write_error",
                        "auth",
                        where="username_prompt",
                        error=str(e),
                    )
                    return False

                try:
                    raw = await asyncio.wait_for(
                        reader.readline(), timeout=READ_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    await self.session.log(
                        "login.timeout", "auth", message="username read timed out"
                    )
                    # don't immediately count as a failed attempt; re-prompt
                    attempts += 0
                    continue
                except Exception as e:
                    await self.session.log("login.read_error", "auth", error=str(e))
                    return False

                # log raw read for diagnosis
                await self.session.log("login.raw", "auth", raw_repr=repr(raw))

                # explicit EOF -> client closed (telnetlib3 may return '' or None)
                if raw is None or raw == "":
                    await self.session.log("login.eof", "auth", raw=raw)
                    return False

                username = raw.rstrip("\r\n")
                await self.session.log(
                    "login.prompt", "auth", prompt="login", username=username
                )

                # prompt for password
                await self.session.log(
                    "auth.step", "auth", step="prompt_password", attempt=attempts
                )
                try:
                    writer.write("\r\nPassword: ")
                    await writer.drain()
                except Exception as e:
                    await self.session.log(
                        "auth.write_error",
                        "auth",
                        where="password_prompt",
                        error=str(e),
                    )
                    return False

                try:
                    rawp = await asyncio.wait_for(
                        reader.readline(), timeout=READ_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    await self.session.log(
                        "login.timeout", "auth", message="password read timed out"
                    )
                    continue
                except Exception as e:
                    await self.session.log("login.read_error", "auth", error=str(e))
                    return False

                await self.session.log("login.raw", "auth", rawp_repr=repr(rawp))
                if rawp is None or rawp == "":
                    await self.session.log("login.eof", "auth", raw=rawp)
                    return False

                writer.write("\r\n")
                await writer.drain()

                password = rawp.rstrip("\r\n")

                # Stub: accept all credentials. Real implementation: check userdb.
                success = True
                await self.session.log(
                    "login.attempt",
                    "auth",
                    username=username or "",
                    success=bool(success),
                )
                if success:
                    self.session.username = username or "guest"
                    await self.session.log(
                        "auth.success", "auth", username=self.session.username
                    )
                    return True

                attempts += 1
                await asyncio.sleep(self.fail_delay)

            await self.session.log("auth.exhausted", "auth", attempts=attempts)
            return False
        except Exception as exc:
            try:
                await self.session.log("login.error", "auth", error=str(exc))
            except Exception:
                pass
            return False

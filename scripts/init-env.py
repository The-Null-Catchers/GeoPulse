"""Write .env once with fresh secrets. Never overwrite an existing environment."""

import secrets
from pathlib import Path

file = Path(__file__).resolve().parent.parent / ".env"
with file.open("x") as stream:
    stream.write(
        f"POSTGRES_PASSWORD={secrets.token_hex(24)}\nJWT_SECRET={secrets.token_hex(48)}\nSITE_ADDRESS=:80\nCORS_ORIGINS=http://localhost\nCOOKIE_SECURE=false\nROUTING_URL=\nSIMULATOR_EMAIL=demo@example.test\nSIMULATOR_PASSWORD={secrets.token_hex(16)}\n"
    )
file.chmod(0o600)
print("Created .env. Configure HTTPS, origin and secure cookies before production.")

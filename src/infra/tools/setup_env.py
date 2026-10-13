#!/usr/bin/env python3
"""Create a local development configuration without overwriting existing secrets."""
import os
from pathlib import Path
import secrets


def main():
    root = Path(__file__).resolve().parents[3]
    target = root / '.env'
    content = (root / '.env.example').read_text(encoding='utf-8')
    content = content.replace('CHANGE_ME_USE_SETUP_ENV', secrets.token_urlsafe(36))
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print('.env already exists; kept unchanged. Replace a placeholder token manually if necessary.')
        return
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(content)
    print('Created .env with a generated development token. Token is not printed.')


if __name__ == '__main__':
    main()

"""Prepare local development configuration without printing secret values."""
import argparse
from getpass import GetPassWarning, getpass
from pathlib import Path
import secrets
import warnings
from dotenv import dotenv_values, set_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-login', action='store_true', help='Enable local-only access without a login prompt.')
    parser.add_argument('--prompt-password', action='store_true', help='Prompt locally without echoing the application password.')
    options = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    path = root / '.env'
    if not path.exists():
        path.write_text((root / '.env.example').read_text(encoding='utf-8'), encoding='utf-8')
    values = dotenv_values(path)
    if options.no_login:
        set_key(path, 'DJANGO_LOCAL_NO_LOGIN', 'true')
    if not values.get('DJANGO_SECRET_KEY') or len(values['DJANGO_SECRET_KEY']) < 50:
        set_key(path, 'DJANGO_SECRET_KEY', secrets.token_urlsafe(64))
        print('Generated a secure local Django secret (value withheld).')
    for key, expected in {
        'DJANGO_DEBUG': 'false',
        'DJANGO_LOCAL_HTTP': 'true',
        'DJANGO_ALLOWED_HOSTS': 'localhost,127.0.0.1',
    }.items():
        if not values.get(key):
            set_key(path, key, expected)
    if options.prompt_password:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', GetPassWarning)
                password = getpass('Application account password (not root): ')
        except GetPassWarning:
            parser.error('Hidden input is unavailable. Edit DB_PASSWORD in your local .env instead.')
        if not password:
            parser.error('The application password cannot be empty; existing credentials were preserved.')
        set_key(path, 'DB_PASSWORD', password)
        print('Application password stored locally (value withheld).')
    else:
        print('Local configuration prepared. SQLite does not require a database password.')


if __name__ == '__main__':
    main()

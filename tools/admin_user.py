"""Initialize/reset the single administrator on the server; password never echoed."""
import argparse
import getpass
from backend import news, admin_auth


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', default='admin')
    args = parser.parse_args()
    password = getpass.getpass('New admin password (12+ characters): ')
    if password != getpass.getpass('Repeat password: '):
        parser.error('Passwords differ')
    news.initialize()
    admin_auth.initialize_user(args.username, password)
    print('Administrator initialized; existing sessions revoked')

#!/usr/bin/env python3
"""CLI helper to merge trips for development and operations.

Usage:
  python merge_trips_cli.py --target 1 --source 3 --user admin --pass password123

Options:
  --no-auth    : Skip admin authentication (ONLY allowed when DEV_ALLOW_ADMIN_BYPASS=1)
  --force      : Skip interactive confirmation (still requires env bypass for no-auth)
"""
import os
import argparse
from booking_engine import merge_trips, admin_merge_trips


def confirm(prompt):
    try:
        resp = input(prompt + ' [y/N]: ').strip().lower()
    except EOFError:
        return False
    return resp in ('y', 'yes')


def main():
    parser = argparse.ArgumentParser(description='Merge two trips (admin operation)')
    parser.add_argument('--target', type=int, required=True, help='Target trip ID')
    parser.add_argument('--source', type=int, required=True, help='Source trip ID')
    parser.add_argument('--user', type=str, help='Admin username (optional)')
    parser.add_argument('--pass', dest='password', type=str, help='Admin password (optional)')
    parser.add_argument('--no-auth', action='store_true', help='Bypass admin auth (requires DEV_ALLOW_ADMIN_BYPASS=1)')
    parser.add_argument('--force', action='store_true', help='Do not prompt for confirmation')

    args = parser.parse_args()

    if args.no_auth and os.environ.get('DEV_ALLOW_ADMIN_BYPASS') != '1':
        print('Refusing to bypass auth: set DEV_ALLOW_ADMIN_BYPASS=1 to allow --no-auth in dev.')
        return

    if not args.force:
        ok = confirm(f"About to merge source trip {args.source} into target trip {args.target}. Proceed?")
        if not ok:
            print('Aborted by user.')
            return

    if args.no_auth:
        # Directly call merge_trips without authentication
        print('Bypassing auth and invoking merge_trips directly (DEV mode).')
        success = merge_trips(args.target, args.source)
    else:
        if not args.user or not args.password:
            print('Username and password required when not using --no-auth.')
            return
        print('Attempting authenticated admin merge...')
        success = admin_merge_trips(args.user, args.password, target_trip_id=args.target, source_trip_id=args.source)

    print(f'Merge result: {success}')


if __name__ == '__main__':
    main()

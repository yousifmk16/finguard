"""
Quick script to create a FinGuard user account.

Usage (from the backend/ folder):
    python scripts/create_user.py
or with args:
    python scripts/create_user.py --email you@example.com --password secret --role admin
"""

import argparse
import os
import sys
from pathlib import Path

# Make sure the backend package is importable when run from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import sqlalchemy
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password
from app.db.base import Base
from app.db.models.user import UserRow


def get_engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL is not set. Copy backend/.env.example to backend/.env and fill it in.")
        sys.exit(1)
    return create_engine(url, pool_pre_ping=True)


def main():
    parser = argparse.ArgumentParser(description="Create a FinGuard user account")
    parser.add_argument("--email",    default="admin@finguard.local")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--role",     default="admin", choices=["admin", "analyst"])
    args = parser.parse_args()

    engine = get_engine()

    # Create the users table if it doesn't exist yet
    Base.metadata.create_all(engine, tables=[UserRow.__table__])

    Session = sessionmaker(bind=engine)
    with Session() as session:
        existing = session.execute(
            sqlalchemy.select(UserRow).where(UserRow.email == args.email.lower())
        ).scalar_one_or_none()

        if existing:
            print(f"User '{args.email}' already exists (role: {existing.role}).")
            print("If you want to reset the password, delete the user from the DB first.")
            sys.exit(0)

        user = UserRow(
            email=args.email.lower(),
            hashed_password=hash_password(args.password),
            role=args.role,
        )
        session.add(user)
        session.commit()

    print()
    print("User created successfully!")
    print(f"  Email   : {args.email}")
    print(f"  Password: {args.password}")
    print(f"  Role    : {args.role}")
    print()
    print("You can now log in at http://localhost:3000")


if __name__ == "__main__":
    main()

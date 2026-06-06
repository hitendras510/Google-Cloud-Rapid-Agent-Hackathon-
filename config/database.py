"""
DevSentinel — Database Connection
Singleton MongoDB client with collection accessors.
"""

import os
import pymongo
from pymongo import MongoClient
from pymongo.database import Database

_client: MongoClient = None
_db: Database = None


def get_db() -> Database:
    """Returns singleton MongoDB database instance."""
    global _client, _db
    if _db is None:
        uri = os.environ.get("MONGODB_URI", "")
        if not uri:
            raise ValueError("MONGODB_URI environment variable is not set.")
        _client = MongoClient(uri)
        db_name = os.environ.get("MONGODB_DB_NAME", "devsentiinel")
        _db = _client[db_name]
        print(f"[DB] Connected to MongoDB: {db_name}")
    return _db


def get_collection(name: str):
    """Shortcut to get a specific collection."""
    return get_db()[name]


def ping():
    """Test the connection."""
    try:
        get_db().command("ping")
        return True
    except Exception as e:
        print(f"[DB] Ping failed: {e}")
        return False

"""Ping MongoDB using backend/.env:  python scripts/check_mongo_connection.py"""
from pathlib import Path

from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
uri = os.getenv("MONGO_URI")
client = MongoClient(
    uri,
    tls=True,
    tlsAllowInvalidCertificates=False,
    serverSelectionTimeoutMS=30000,
    connectTimeoutMS=30000,
)
try:
    client.admin.command('ping')
    print("[OK] Ping successful! Connected to MongoDB Atlas")
except Exception as e:
    print("[ERROR]", e)
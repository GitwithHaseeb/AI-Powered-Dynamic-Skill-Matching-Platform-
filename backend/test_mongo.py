from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()
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
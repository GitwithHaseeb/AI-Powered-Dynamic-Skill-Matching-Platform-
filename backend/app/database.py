import asyncio
from typing import Any, Optional

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings


def _configure_public_dns_for_srv() -> None:
    """
    Atlas mongodb+srv:// needs SRV DNS. Campus/ISP resolvers (e.g. 10.x) often time out —
    use public DNS so `uvicorn` starts reliably from VS Code on any network.
    """
    try:
        import dns.resolver

        resolver = dns.resolver.Resolver(configure=False)
        resolver.nameservers = ["8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1"]
        resolver.lifetime = 20.0
        resolver.timeout = 5.0
        dns.resolver.default_resolver = resolver
    except Exception:
        # dnspython missing or OS blocks custom resolver — fall back to system DNS.
        pass


class Database:
    client: Optional[AsyncIOMotorClient] = None
    db = None

    async def connect(self):
        uri = settings.mongo_url
        if uri.startswith("mongodb+srv://"):
            _configure_public_dns_for_srv()

        kwargs: dict[str, Any] = {
            "serverSelectionTimeoutMS": 20_000,
            "connectTimeoutMS": 20_000,
            "socketTimeoutMS": 30_000,
        }
        use_tls = uri.startswith("mongodb+srv://") or "tls=true" in uri or "ssl=true" in uri
        if use_tls:
            kwargs["tls"] = True
            kwargs["tlsAllowInvalidCertificates"] = False
            kwargs["tlsCAFile"] = certifi.where()
        if settings.MONGODB_TLS_INSECURE:
            kwargs["tlsInsecure"] = True

        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                self.client = AsyncIOMotorClient(uri, **kwargs)
                self.db = self.client[settings.MONGODB_DB_NAME]
                await self.client.admin.command("ping")
                return
            except Exception as exc:
                last_err = exc
                if self.client:
                    self.client.close()
                    self.client = None
                if attempt < 3:
                    print(
                        f"[WARN] MongoDB connect attempt {attempt}/3 failed "
                        f"({type(exc).__name__}), retrying..."
                    )
                    await asyncio.sleep(2 * attempt)

        assert last_err is not None
        raise last_err

    async def disconnect(self):
        if self.client:
            self.client.close()
            print("Disconnected from MongoDB")

    def get_collection(self, collection_name: str):
        return self.db[collection_name]


db = Database()


def get_users_collection():
    return db.get_collection("users")


def get_projects_collection():
    return db.get_collection("projects")


def get_tasks_collection():
    return db.get_collection("tasks")


def get_skills_collection():
    return db.get_collection("skills")


def get_documents_collection():
    return db.get_collection("srs_documents")


def get_teams_collection():
    return db.get_collection("teams")


def get_activity_logs_collection():
    return db.get_collection("activity_logs")


def get_recommendations_collection():
    return db.get_collection("recommendations")

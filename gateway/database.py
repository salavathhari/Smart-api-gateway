from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
import redis.asyncio as redis
from motor.motor_asyncio import AsyncIOMotorClient
from gateway.config import settings

# --- SQL Database (Postgres) ---
SQL_DATABASE_URL = os.getenv(
    "SQL_DATABASE_URL",
    "postgresql://gateway:gateway_password@localhost:5432/gateway_logs"
)

engine = create_engine(
    SQL_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)

# --- NoSQL & Cache (MongoDB & Redis) ---
class DatabaseManager:
    def __init__(self):
        self.client = AsyncIOMotorClient(
            settings.database_url,
            serverSelectionTimeoutMS=5000
        )
        self.db = self.client.get_default_database()
        self.redis = None

    async def connect(self):
        try:
            await self.client.admin.command('ping')
            print("✅ MongoDB connected")
        except Exception as e:
            print(f"⚠️  Database connection failed (MongoDB): {e}")
        
        try:
            self.redis = redis.from_url(settings.redis_url, decode_responses=True)
            await self.redis.ping()
            print("✅ Redis connected")
        except Exception as e:
            print(f"⚠️  Redis connection failed: {e}")

    async def disconnect(self):
        if self.redis:
            await self.redis.close()
        self.client.close()
        print("🛑 Database & Redis disconnected")

db_manager = DatabaseManager()

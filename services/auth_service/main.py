"""
Mock Auth Service — listens on port 9001.
"""

import datetime
from typing import Optional

import jwt
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Shared secret with Gateway
SECRET_KEY = "super-secret-gateway-key-change-me-in-production"
ALGORITHM = "HS256"

app = FastAPI(title="Auth Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Mock Auth Service is running", "endpoints": ["/auth/login", "/auth/me", "/auth/health"]}


@app.get("/auth/health")
@app.get("/health")
async def health():
    return {"service": "auth", "status": "ok"}


@app.post("/auth/login")
async def login(body: dict):
    username = body.get("username", "")
    password = body.get("password", "")
    
    # Simple hardcoded check for now
    if username == "admin" and password == "secret":
        payload = {
            "sub": username,
            "roles": ["admin", "user"],
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        }
        token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
        return {"access_token": token, "token_type": "bearer"}
    
    return JSONResponse(status_code=401, content={"error": "invalid_credentials"})


@app.get("/auth/me")
async def me(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"user": payload["sub"], "roles": payload["roles"], "service": "auth"}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.post("/auth/logout")
async def logout():
    return {"message": "logged out"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9001, log_level="warning")

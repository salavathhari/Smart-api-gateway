"""
Mock Auth Service — listens on port 9001.
Simulates a real auth backend so you can test the gateway without external deps.
"""

import uvicorn
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from typing import Optional

app = FastAPI(title="Auth Service (Mock)", version="1.0.0")


@app.get("/auth/health")
async def health():
    return {"service": "auth", "status": "ok"}


@app.post("/auth/login")
async def login(body: dict):
    username = body.get("username", "")
    password = body.get("password", "")
    if username == "admin" and password == "secret":
        return {"token": "mock-jwt-token-abc123", "user": username}
    return JSONResponse(status_code=401, content={"error": "invalid_credentials"})


@app.get("/auth/me")
async def me(authorization: Optional[str] = Header(None)):
    if not authorization or "mock-jwt-token" not in authorization:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return {"user": "admin", "roles": ["admin", "user"], "service": "auth"}


@app.post("/auth/logout")
async def logout():
    return {"message": "logged out"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9001, log_level="warning")

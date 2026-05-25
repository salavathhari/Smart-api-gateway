"""
Mock Chat Service — listens on port 9002.
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Chat Service (Mock)", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Mock Chat Service is running", "endpoints": ["/chat/rooms", "/chat/health"]}


@app.get("/chat/health")
async def health():
    return {"service": "chat", "status": "ok"}


@app.get("/chat/rooms")
async def list_rooms():
    return {
        "rooms": [
            {"id": "room-1", "name": "General", "members": 42},
            {"id": "room-2", "name": "Engineering", "members": 15},
        ]
    }


@app.post("/chat/rooms/{room_id}/messages")
async def send_message(room_id: str, body: dict):
    return {
        "id": "msg-999",
        "room": room_id,
        "text": body.get("text", ""),
        "author": body.get("author", "anonymous"),
        "service": "chat",
    }


@app.get("/chat/rooms/{room_id}/messages")
async def get_messages(room_id: str):
    return {
        "room": room_id,
        "messages": [
            {"id": "msg-1", "text": "Hello!", "author": "alice"},
            {"id": "msg-2", "text": "Hi there!", "author": "bob"},
        ],
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9002, log_level="warning")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, List
import psycopg2
import uuid
import datetime
import hashlib

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_connection():
    return psycopg2.connect(
        dbname="Educonnect",
        user="postgres",
        password="12345678",
        host="localhost",
        port=5432
    )

class ConnectionManager:
    def __init__(self):
        self.active_conversations: Dict[str, List[WebSocket]] = {}
        self.user_sockets: Dict[str, List[WebSocket]] = {}

    async def connect(self, conversation_id: str, username: str, websocket: WebSocket):
        await websocket.accept()
        # for messages
        if conversation_id not in self.active_conversations:
            self.active_conversations[conversation_id] = []
        self.active_conversations[conversation_id].append(websocket)
        # for conversation push
        if username not in self.user_sockets:
            self.user_sockets[username] = []
        self.user_sockets[username].append(websocket)

    def disconnect(self, conversation_id: str, username: str, websocket: WebSocket):
        if conversation_id in self.active_conversations:
            self.active_conversations[conversation_id].remove(websocket)
        if username in self.user_sockets:
            self.user_sockets[username].remove(websocket)

    async def broadcast_message(self, conversation_id: str, message: dict):
        for connection in self.active_conversations.get(conversation_id, []):
            await connection.send_json(message)

    async def notify_user(self, username: str, payload: dict):
        for conn in self.user_sockets.get(username, []):
            await conn.send_json(payload)

manager = ConnectionManager()

class LoginRequest(BaseModel):
    username: str
    password: str

class StartConversationRequest(BaseModel):
    user1: str
    user2: str

@app.post("/check_login")
def check_login(req: LoginRequest):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username = %s", (req.username,))
    row = cur.fetchone()
    conn.close()
    if row and row[0] == hashlib.sha256(req.password.encode()).hexdigest():
        return {"success": True}
    return {"success": False}, 401

@app.get("/search_users")
def search_users(keyword: str, exclude: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT username, name FROM users
        WHERE username != %s AND (username ILIKE %s OR name ILIKE %s)
        LIMIT 20
    """, (exclude, f"%{keyword}%", f"%{keyword}%"))
    results = cur.fetchall()
    conn.close()
    return [{"username": r[0], "name": r[1]} for r in results]

@app.post("/start_conversation")
def start_conversation(data: StartConversationRequest):
    user1 = data.user1
    user2 = data.user2
    conn = get_connection()
    cur = conn.cursor()
    # Check if conversation already exists
    cur.execute("""
        SELECT c.conversation_id
        FROM conversations c
        JOIN participants_conversation p1 ON c.conversation_id = p1.conversation_id
        JOIN users u1 ON p1.user_id = u1.user_id
        JOIN participants_conversation p2 ON c.conversation_id = p2.conversation_id
        JOIN users u2 ON p2.user_id = u2.user_id
        WHERE u1.username = %s AND u2.username = %s
        GROUP BY c.conversation_id
        HAVING COUNT(DISTINCT u1.user_id || u2.user_id) = 1
    """, (user1, user2))
    row = cur.fetchone()
    if row:
        conv_id = row[0]
    else:
        # Create new conversation
        conv_id = "conv_" + str(uuid.uuid4())[:8]
        conv_name = f"Chat: {user1}, {user2}"
        cur.execute("INSERT INTO conversations (conversation_id, conversation_name) VALUES (%s, %s)", (conv_id, conv_name))
        for u in (user1, user2):
            cur.execute("SELECT user_id FROM users WHERE username = %s", (u,))
            user_id = cur.fetchone()[0]
            cur.execute("INSERT INTO participants_conversation (conversation_id, user_id) VALUES (%s, %s)", (conv_id, user_id))
        conn.commit()
        # Notify user2 if online
        import asyncio
        asyncio.create_task(manager.notify_user(user2, {
            "type": "new_conversation",
            "conversation_id": conv_id,
            "conversation_name": conv_name
        }))
    conn.close()
    return {"conversation_id": conv_id}

@app.get("/conversations")
def get_conversations(user: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.conversation_id, c.conversation_name
        FROM conversations c
        JOIN participants_conversation p ON c.conversation_id = p.conversation_id
        JOIN users u ON u.user_id = p.user_id
        WHERE u.username = %s
    """, (user,))
    rows = cur.fetchall()
    conn.close()
    return [{"id": row[0], "name": row[1]} for row in rows]

@app.get("/messages")
def get_messages(conversation_id: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT u.username, m.message_text, m.created_at
        FROM messages m
        JOIN users u ON u.user_id = m.sender_id
        WHERE conversation_id = %s
        ORDER BY m.created_at ASC
    """, (conversation_id,))
    rows = cur.fetchall()
    conn.close()
    return [{"sender": row[0], "message": row[1], "created_at": str(row[2])} for row in rows]

@app.websocket("/ws/{conversation_id}/{username}")
async def websocket_endpoint(websocket: WebSocket, conversation_id: str, username: str):
    # Nếu conversation_id là 'none', thì chỉ dùng cho push notification
    await websocket.accept()
    if conversation_id != "none":
        if conversation_id not in manager.active_conversations:
            manager.active_conversations[conversation_id] = []
        manager.active_conversations[conversation_id].append(websocket)

    if username not in manager.user_sockets:
        manager.user_sockets[username] = []
    manager.user_sockets[username].append(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            message_text = data.get("message")
            if message_text and conversation_id != "none":
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("SELECT user_id FROM users WHERE username = %s", (username,))
                sender_id = cur.fetchone()[0]
                cur.execute("""
                    INSERT INTO messages (conversation_id, sender_id, message_text, created_at)
                    VALUES (%s, %s, %s, %s)
                """, (conversation_id, sender_id, message_text, datetime.datetime.now(datetime.timezone.utc)))
                conn.commit()
                conn.close()

                await manager.broadcast_message(conversation_id, {
                    "sender": username,
                    "message": message_text,
                    "created_at": str(datetime.datetime.now())
                })
    except WebSocketDisconnect:
        if conversation_id != "none":
            if websocket in manager.active_conversations.get(conversation_id, []):
                manager.active_conversations[conversation_id].remove(websocket)
        if websocket in manager.user_sockets.get(username, []):
            manager.user_sockets[username].remove(websocket)

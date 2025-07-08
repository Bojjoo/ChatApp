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
    cur.execute("SELECT user_id, password FROM users WHERE username = %s", (req.username,))
    row = cur.fetchone()
    conn.close()
    if row and row[1] == req.password:   #hashlib.sha256(req.password.encode()).hexdigest():
        return {"success": True, "user_id": row[0]}
    return {"success": False}, 401

@app.get("/search_users")
def search_users(keyword: str, exclude: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT username, name, user_id, avatar_url FROM users
        WHERE user_id != %s AND (username ILIKE %s OR name ILIKE %s)
        LIMIT 20
    """, (exclude, f"%{keyword}%", f"%{keyword}%"))
    results = cur.fetchall()
    conn.close()
    return [{
        "username": r[0],
        "name": r[1],
        "user_id": r[2],
        "avatar_url": r[3]
    } for r in results]

@app.post("/start_conversation")
async def start_conversation(data: StartConversationRequest):
    user1 = data.user1
    user2 = data.user2
    conn = get_connection()
    cur = conn.cursor()

    # Kiểm tra xem đã có cuộc trò chuyện giữa 2 người này chưa
    cur.execute("""
        SELECT c.conversation_id
        FROM conversations c
        JOIN participants_conversation p1 ON c.conversation_id = p1.conversation_id
        JOIN participants_conversation p2 ON c.conversation_id = p2.conversation_id
        WHERE p1.user_id = %s AND p2.user_id = %s
        GROUP BY c.conversation_id
        HAVING COUNT(DISTINCT p1.user_id || p2.user_id) = 1
    """, (user1, user2))
    row = cur.fetchone()
    if row:
        conv_id = row[0]
    else:
        # Tạo cuộc trò chuyện mới
        conv_id = "conv_" + str(uuid.uuid4())[:8]
        conv_name = f"Chat: {user1}, {user2}"
        cur.execute("INSERT INTO conversations (conversation_id, conversation_name) VALUES (%s, %s)",
                    (conv_id, conv_name))
        for uid in (user1, user2):
            cur.execute("INSERT INTO participants_conversation (conversation_id, user_id) VALUES (%s, %s)", (conv_id, uid))
        conn.commit()

        # Gửi notify đến user2 nếu đang online
        await manager.notify_user(user2, {
            "type": "new_conversation",
            "conversation_id": conv_id,
            "conversation_name": conv_name
        })
    conn.close()
    return {"conversation_id": conv_id}

@app.get("/conversations")
def get_conversations(user: str):  # user là user_id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            c.conversation_id,
            u2.username,
            u2.name,
            u2.avatar_url
        FROM conversations c
        JOIN participants_conversation p1 ON c.conversation_id = p1.conversation_id
        JOIN users u1 ON p1.user_id = u1.user_id
        JOIN participants_conversation p2 ON c.conversation_id = p2.conversation_id
        JOIN users u2 ON p2.user_id = u2.user_id
        WHERE u1.user_id = %s AND u2.user_id != %s
    """, (user, user))
    rows = cur.fetchall()
    conn.close()
    return [{
        "id": r[0],
        "other_username": r[1],
        "other_name": r[2],
        "avatar_url": r[3]
    } for r in rows]


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

@app.websocket("/ws/user/{user_id}")
async def user_websocket(websocket: WebSocket, user_id: str):
    await websocket.accept()

    if user_id not in manager.user_sockets:
        manager.user_sockets[user_id] = []
    manager.user_sockets[user_id].append(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "chat":
                conversation_id = data.get("conversation_id")
                message_text = data.get("message")
                if not conversation_id or not message_text:
                    continue

                conn = get_connection()
                cur = conn.cursor()

                # Ghi vào bảng messages
                cur.execute("""
                    INSERT INTO messages (conversation_id, sender_id, message_text, created_at)
                    VALUES (%s, %s, %s, %s)
                """, (conversation_id, user_id, message_text, datetime.datetime.now(datetime.timezone.utc)))
                conn.commit()

                # Lấy danh sách participant user_ids và usernames
                cur.execute("""
                    SELECT u.user_id, u.username, u.name
                    FROM participants_conversation pc
                    JOIN users u ON pc.user_id = u.user_id
                    WHERE pc.conversation_id = %s
                """, (conversation_id,))
                rows = cur.fetchall()

                # Tách danh sách user_id, username khác người gửi
                participants = [(r[0], r[1], r[2]) for r in rows if r[0] != user_id]
                username_map = {r[0]: r[1] for r in rows}  # user_id -> username
                name_map = {r[0]: r[2] for r in rows}      # user_id -> name

                conn.close()

                # Tên cuộc trò chuyện tạm thời
                conversation_name = f"Chat with {', '.join([p[2] for p in participants])}"

                for pid, uname, _ in participants:
                    # Gửi tin nhắn
                    await manager.notify_user(pid, {
                        "type": "chat",
                        "conversation_id": conversation_id,
                        "sender": user_id,
                        "message": message_text,
                        "created_at": str(datetime.datetime.now())
                    })

                    # Gửi "new_conversation"
                    await manager.notify_user(pid, {
                        "type": "new_conversation",
                        "conversation_id": conversation_id,
                        "conversation_name": conversation_name
                    })

                # Gửi về cho chính người gửi
                await websocket.send_json({
                    "type": "chat",
                    "conversation_id": conversation_id,
                    "sender": user_id,
                    "message": message_text,
                    "created_at": str(datetime.datetime.now())
                })

    except WebSocketDisconnect:
        if websocket in manager.user_sockets.get(user_id, []):
            manager.user_sockets[user_id].remove(websocket)

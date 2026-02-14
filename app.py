from flask import Flask, render_template, request, redirect, abort, session, url_for, jsonify
from markupsafe import Markup
from datetime import datetime, timezone, timedelta
import os
import re
import random
import time
import httpx
from supabase import create_client, Client
from datetime import datetime, timezone
import uuid
from flask_cors import CORS
from flask import flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

# ==============================
# Supabase Configuration
# ==============================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

print("URL:", SUPABASE_URL)
print("KEY length:", len(SUPABASE_KEY) if SUPABASE_KEY else "None")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing Supabase environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==============================
# Flask App Config
# ==============================

# FIX: Proper session configuration for production
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecretkey")
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_SECURE'] = True  # Enable for HTTPS (Render uses HTTPS)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Important for cross-site requests
app.config['SESSION_COOKIE_NAME'] = 'chronicle_session'




# FIX: Enable CORS if needed
CORS(app, supports_credentials=True, origins=["*"])


def safe_supabase_call(fn, *, retries=2, delay=0.2):
    for attempt in range(retries + 1):
        try:
            return fn()
        except (httpx.ReadError, httpx.RemoteProtocolError, Exception) as e:
            msg = str(e)
            if ("[Errno 35]" in msg or
                "Resource temporarily unavailable" in msg or
                "RemoteProtocolError" in msg or
                "COMPRESSION_ERROR" in msg or
                "PROTOCOL_ERROR" in msg):
                if attempt < retries:
                    time.sleep(delay * (attempt + 1) * (1 + random.random()))
                    continue
                print("safe_supabase_call: giving up after retries:", msg)
                class Dummy:
                    data = []
                return Dummy()
            else:
                raise


# ==============================
# Markdown Parser
# ==============================
def parse_markdown(text):
    """Simple markdown parser"""
    lines = text.split('\n')
    html = []
    in_list = False
    
    for line in lines:
        stripped = line.strip()
        
        if not stripped:
            if in_list:
                html.append('</ul>')
                in_list = False
            html.append('<br>')
            continue
        
        # Headers
        if stripped.startswith('#### '):
            html.append(f'<h4>{stripped[5:]}</h4>')
        elif stripped.startswith('### '):
            html.append(f'<h3>{stripped[4:]}</h3>')
        elif stripped.startswith('## '):
            html.append(f'<h2>{stripped[3:]}</h2>')
        elif stripped.startswith('# '):
            html.append(f'<h1>{stripped[2:]}</h1>')
        
        # Lists
        elif stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list:
                html.append('<ul>')
                in_list = True
            html.append(f'<li>{stripped[2:]}</li>')
        
        # Regular paragraph
        else:
            if in_list:
                html.append('</ul>')
                in_list = False
            # Bold
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)
            # Italic
            text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
            html.append(f'<p>{text}</p>')
    
    if in_list:
        html.append('</ul>')
    
    return ''.join(html)

# ==============================
# Authentication Routes
# ==============================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()
        is_login = request.form.get('is_login') == 'true'

        if not username or not password:
            flash('Username and password required', 'error')
            return redirect(url_for('login'))

        try:
            if is_login:
                # 🔹 LOGIN MODE
                resp = supabase.table("profiles") \
                    .select("id, name, password") \
                    .eq("name", username) \
                    .eq("password", password) \
                    .execute()

                if not resp.data:
                    flash('Invalid username or password', 'error')
                    return redirect(url_for('login'))

                user = resp.data[0]
                user_id = user['id']

            else:
                # 🔹 SIGNUP MODE
                exists = supabase.table("profiles") \
                    .select("id") \
                    .eq("name", username) \
                    .execute()

                if exists.data:
                    flash('Username already exists. Please login.', 'error')
                    return redirect(url_for('login'))

                user_id = str(uuid.uuid4())

                supabase.table("profiles").insert({
                    "id": user_id,
                    "name": username,
                    "password": password,  # ⚠️ hash in real app
                    "online": True,
                    "last_seen": datetime.now(timezone.utc).isoformat()
                }).execute()

            # ✅ COMMON SESSION LOGIC - Use consistent session keys
            session.permanent = True
            session['chat_user_id'] = user_id  # ← Consistent key
            session['chat_username'] = username  # ← Consistent key

            # Update online status
            supabase.table("profiles").update({
                "online": True,
                "last_seen": datetime.now(timezone.utc).isoformat()
            }).eq("id", user_id).execute()

            print(f"✅ Login successful - User: {username}, ID: {user_id}")
            print(f"✅ Session keys: {list(session.keys())}")

            return redirect(url_for('quickchat'))

        except Exception as e:
            print(f"❌ Login error: {str(e)}")
            flash(f'Error: {str(e)}', 'error')
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/api/chat/user')
def get_current_chat_user():
    """Get current chat user info."""
    user_id = session.get('chat_user_id')
    print("[API /chat/user] Checking session...")
    print("[API /chat/user] Session keys:", list(session.keys()))
    print("[API /chat/user] User ID from session:", user_id)

    if not user_id:
        print("❌ [API /chat/user] No user_id in session, returning 401")
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        resp = safe_supabase_call(
            lambda: supabase.table("profiles")
            .select("id, name, online")
            .eq("id", user_id)
            .execute()
        )
        user_list = getattr(resp, "data", []) or []
        if not user_list:
            print(f"❌ [API /chat/user] Profile not found for user_id: {user_id}")
            # degrade gracefully: basic info from session
            return jsonify({
                "id": user_id,
                "username": session.get("chat_username", "You"),
                "online": True
            }), 200

        user = user_list[0]
        print(f"✅ [API /chat/user] Found user:", user.get("name"))
        return jsonify({
            "id": user["id"],
            "username": user["name"],
            "online": user["online"],
        }), 200
    except Exception as e:
        import traceback
        print("❌ [API /chat/user] Error:", e)
        print(traceback.format_exc())
        # Last resort: still return something so UI doesn't break
        return jsonify({
            "id": user_id,
            "username": session.get("chat_username", "You"),
            "online": True
        }), 200


@app.route("/chat/logout")
def chat_logout():
    """Logout - FIXED to use correct session key"""
    user_id = session.get('chat_user_id')  # ← FIXED: Use correct session key
    
    if user_id:
        try:
            supabase.table("profiles").update({
                "online": False,
                "last_seen": datetime.now(timezone.utc).isoformat()
            }).eq("id", user_id).execute()
            print(f"✅ User {user_id} logged out and set offline")
        except Exception as e:
            print(f"❌ Logout error: {e}")

    session.clear()
    return redirect(url_for('login'))


# ==============================
# Routes: QuickChat
# ==============================

@app.route("/quickchat")
def quickchat():
    """QuickChat page - FIXED to use correct session keys"""
    user_id = session.get('chat_user_id')  # ← FIXED: Use correct session key
    
    print(f"[quickchat] Checking session...")
    print(f"[quickchat] Session keys: {list(session.keys())}")
    print(f"[quickchat] User ID: {user_id}")
    
    if not user_id:
        print(f"❌ [quickchat] No user_id in session, redirecting to login")
        return redirect("/login")

    # Update online status and last_seen
    try:
        supabase.table("profiles").update({
            "online": True,
            "last_seen": datetime.now(timezone.utc).isoformat()
        }).eq("id", user_id).execute()
        print(f"✅ [quickchat] Updated online status for user: {user_id}")
    except Exception as e:
        print(f"❌ [quickchat] Online update error: {e}")

    # Fetch other online users
    try:
        resp = supabase.table("profiles").select("*").eq("online", True).neq("id", user_id).execute()
        users_data = resp.data or []
        print(f"✅ [quickchat] Found {len(users_data)} other online users")
    except Exception as e:
        print(f"❌ [quickchat] Fetch users error: {e}")
        users_data = []

    # Pass current user info to template
    current_user = {
        "id": user_id,
        "username": session.get("chat_username", "You")  # ← FIXED: Use correct session key
    }

    return render_template("quickchat.html", users=users_data, current_user=current_user)


# ==============================
# Chat API Routes
# ==============================
@app.route("/api/chat/users")
def get_chat_users():
    current_id = session.get("chat_user_id")
    if not current_id:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        # 1) Find all active chats this user is in
        chats_resp = safe_supabase_call(
            lambda: supabase.table("active_chats")
            .select("id, participants")
            .eq("status", "active")
            .execute()
        )
        chats = getattr(chats_resp, "data", []) or []

        # Map other_user_id -> chat_id
        partner_to_chat = {}
        for chat in chats:
            parts = chat.get("participants") or []
            if current_id in parts:
                others = [p for p in parts if p != current_id]
                if len(others) == 1:
                    partner_to_chat[others[0]] = chat["id"]

        partner_ids = list(partner_to_chat.keys())
        if not partner_ids:
            return jsonify([]), 200

        # 2) Load partner profiles
        profiles_resp = safe_supabase_call(
            lambda: supabase.table("profiles")
            .select("id, name, online, last_seen")
            .in_("id", partner_ids)
            .execute()
        )
        profiles = getattr(profiles_resp, "data", []) or []

        # 3) Requests info (for badges)
        incoming_resp = safe_supabase_call(
            lambda: supabase.table("chat_requests")
            .select("from_user")
            .eq("to_user", current_id)
            .eq("status", "pending")
            .execute()
        )
        incoming_from = {row["from_user"] for row in (getattr(incoming_resp, "data", []) or [])}

        outgoing_resp = safe_supabase_call(
            lambda: supabase.table("chat_requests")
            .select("to_user")
            .eq("from_user", current_id)
            .eq("status", "pending")
            .execute()
        )
        outgoing_to = {row["to_user"] for row in (getattr(outgoing_resp, "data", []) or [])}

        # 4) Build result list: only accepted chats
        result = []
        for p in profiles:
            uid = p["id"]
            result.append({
                "id": uid,
                "username": p.get("name"),
                "online": p.get("online", False),
                "hasrequest": uid in incoming_from,   # should usually be false if already accepted
                "requestsent": uid in outgoing_to,
                "chatactive": True,
                "chatid": partner_to_chat.get(uid),
            })

        return jsonify(result), 200
    except Exception as e:
        import traceback
        print("API chatusers error", e)
        print(traceback.format_exc())
        return jsonify([]), 200


        
@app.route("/api/chat/requests")
def get_pending_requests():
    current_id = session.get("chat_user_id")
    if not current_id:
        return jsonify({"error": "Not authenticated"}), 401

    print("[/api/chat/requests] current_id:", current_id)
    try:
        resp = safe_supabase_call(
            lambda: supabase.table("chat_requests")
            .select("from_user, created_at, status")
            .eq("to_user", current_id)
            .eq("status", "pending")
            .execute()
        )
        pending = getattr(resp, "data", []) or []
        print("[/api/chat/requests] pending count:", len(pending))
        return jsonify({"count": len(pending)}), 200
    except Exception as e:
        import traceback
        print("API chat/requests error", e)
        print(traceback.format_exc())
        # last resort: do not kill UI, just say 0
        return jsonify({"count": 0}), 200


@app.route("/api/chat/start/<other_user_id>")
def start_chat(other_user_id):
    current_id = session.get("chat_user_id")
    if not current_id:
        return jsonify({"error": "Not authenticated"}), 401

    if not other_user_id or other_user_id == current_id:
        return jsonify({"error": "Invalid other user"}), 400

    try:
        # Deterministic chat id for 1:1 chats
        chat_id = "-".join(sorted([current_id, other_user_id]))

        # Upsert active chat
        supabase.table("active_chats").upsert({
            "id": chat_id,
            "participants": [current_id, other_user_id],
            "status": "active",
        }, on_conflict="id").execute()

        return jsonify({"id": chat_id, "participants": [current_id, other_user_id]}), 200
    except Exception as e:
        print("API chat/start error", e)
        return jsonify({"error": str(e)}), 500

@app.route("/api/chat/messages/<chat_id>")
def get_messages(chat_id):
    current_id = session.get("chat_user_id")
    if not current_id:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        chat_resp = safe_supabase_call(
            lambda: supabase.table("active_chats")
            .select("participants")
            .eq("id", chat_id)
            .execute()
        )
        chat_rows = getattr(chat_resp, "data", []) or []
        if not chat_rows:
            return jsonify({"error": "Chat not found"}), 404

        participants = chat_rows[0].get("participants") or []
        if current_id not in participants:
            return jsonify({"error": "Unauthorized"}), 403

#        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
#
#        messages_resp = safe_supabase_call(
#            lambda: supabase.table("messages")
#            .select("id, chat_id, sender, text, created_at")
#            .eq("chat_id", chat_id)
#            .gte("created_at", cutoff)
#            .order("created_at", desc=False)
#            .execute()
#        )
        messages_resp = safe_supabase_call(
            lambda: supabase.table("messages")
            .select("id, chat_id, sender, text, created_at")
            .eq("chat_id", chat_id)
            .order("created_at", desc=False)
            .execute()
        )


        msg_rows = getattr(messages_resp, "data", []) or []

        now = datetime.now(timezone.utc)
        messages = []
        for msg in msg_rows:
            messages.append({
                "id": msg["id"],
                "text": msg["text"],
                "sender": msg["sender"],
                "sendername": "Unknown",
                "createdat": msg["created_at"],  # raw string from Supabase
                "secondsleft": 30,               # let frontend handle countdown
            })


        return jsonify(messages), 200
    except Exception as e:
        import traceback
        print("API chat/messages error", e)
        print(traceback.format_exc())
        return jsonify([]), 200


@app.route("/api/chat/send", methods=["POST"])
def send_message():
    current_id = session.get("chat_user_id")
    if not current_id:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        data = request.get_json() or {}
        chat_id = data.get("chatid")
        text = (data.get("text") or "").strip()
        if not chat_id or not text:
            return jsonify({"error": "chatid and text required"}), 400

        # verify membership via active_chats
        chat_resp = safe_supabase_call(
            lambda: supabase.table("active_chats")
            .select("participants")
            .eq("id", chat_id)
            .execute()
        )
        rows = getattr(chat_resp, "data", []) or []
        if not rows:
            return jsonify({"error": "Chat not found"}), 404

        participants = rows[0].get("participants") or []
        if current_id not in participants:
            return jsonify({"error": "Unauthorized"}), 403

        message_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        safe_supabase_call(
            lambda: supabase.table("messages").insert({
                "id": message_id,
                "chat_id": chat_id,
                "sender": current_id,
                "text": text,
                "created_at": now,
            }).execute()
        )

        return jsonify({
            "id": message_id,
            "chatid": chat_id,
            "sender": current_id,
            "text": text,
            "createdat": now,
            "secondsleft": 30,
        }), 200
    except Exception as e:
        import traceback
        print("Error sending message", e)
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500



@app.route("/add-friend/<friend_id>")
def add_friend(friend_id):
    """Add friend - FIXED to use correct session key"""
    current_user_id = session.get('chat_user_id')  # ← FIXED
    
    if not current_user_id:
        return redirect("/login")
    try:
        supabase.table("friends").insert({
            "user_id": current_user_id,
            "friend_id": friend_id,
            "status": "pending"
        }).execute()
    except Exception as e:
        print(f"Add friend error: {e}")
    return redirect("/quickchat")
    
    
# ==============
# reques, friend and search
# =================
@app.route("/api/chat/users/search")
def search_chat_users():
    current_id = session.get("chat_user_id")
    if not current_id:
        return jsonify({"error": "Not authenticated"}), 401

    q = (request.args.get("q") or "").strip().lower()
    if not q:
        return jsonify([]), 200

    try:
        # Global search in profiles except myself
        query = supabase.table("profiles") \
            .select("id, name, online, last_seen") \
            .neq("id", current_id) \
            .ilike("name", f"%{q}%")

        resp = safe_supabase_call(lambda: query.execute())
        users = getattr(resp, "data", []) or []

        # Requests info to show Request / Pending / Accept
        incoming_resp = safe_supabase_call(
            lambda: supabase.table("chat_requests")
            .select("from_user")
            .eq("to_user", current_id)
            .eq("status", "pending")
            .execute()
        )
        incoming_from = {row["from_user"] for row in (getattr(incoming_resp, "data", []) or [])}

        outgoing_resp = safe_supabase_call(
            lambda: supabase.table("chat_requests")
            .select("to_user")
            .eq("from_user", current_id)
            .eq("status", "pending")
            .execute()
        )
        outgoing_to = {row["to_user"] for row in (getattr(outgoing_resp, "data", []) or [])}

        # Active chats to decide Open vs Request
        chats_resp = safe_supabase_call(
            lambda: supabase.table("active_chats")
            .select("id, participants")
            .execute()
        )
        active_for_user = {}
        for chat in getattr(chats_resp, "data", []) or []:
            parts = chat.get("participants") or []
            if current_id in parts:
                others = [p for p in parts if p != current_id]
                if len(others) == 1:
                    active_for_user[others[0]] = chat["id"]

        result = []
        for u in users:
            uid = u["id"]
            result.append({
                "id": uid,
                "username": u.get("name"),
                "online": u.get("online", False),
                "hasrequest": uid in incoming_from,
                "requestsent": uid in outgoing_to,
                "chatactive": uid in active_for_user,
                "chatid": active_for_user.get(uid),
            })

        return jsonify(result), 200
    except Exception as e:
        import traceback
        print("API chatusers search error", e)
        print(traceback.format_exc())
        return jsonify([]), 200


@app.route("/api/chat/request", methods=["POST"])
def send_chat_request():
    current_id = session.get("chat_user_id")  # must match login
    if not current_id:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json() or {}
    target_id = data.get("userid")
    if not target_id or target_id == current_id:
        return jsonify({"error": "Invalid target"}), 400

    try:
        supabase.table("chat_requests").insert({
            "from_user": current_id,
            "to_user": target_id,
            "status": "pending",
        }).execute()
        return jsonify({"ok": True}), 200
    except Exception as e:
        print("send_chat_request error", e)
        # on duplicate, still OK
        return jsonify({"ok": True}), 200

@app.route("/api/chat/request/accept", methods=["POST"])
def accept_chat_request():
    current_id = session.get("chat_user_id")
    if not current_id:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json() or {}
    other_id = data.get("userid")
    if not other_id:
        return jsonify({"error": "Missing userid"}), 400

    chat_id = "-".join(sorted([current_id, other_id]))

    # mark request accepted if pending (by id, to avoid unique conflicts)
    try:
        resp = supabase.table("chat_requests") \
            .select("id, status") \
            .eq("from_user", other_id) \
            .eq("to_user", current_id) \
            .execute()
        rows = resp.data or []
        if rows and rows[0]["status"] == "pending":
            supabase.table("chat_requests").update({"status": "accepted"}) \
                .eq("id", rows[0]["id"]).execute()
    except Exception as e:
        print("accept_chat_request update error", e)

    # ensure active chat exists
    try:
        supabase.table("active_chats").upsert({
            "id": chat_id,
            "participants": [current_id, other_id],
            "status": "active",
        }, on_conflict="id").execute()
    except Exception as e:
        print("active_chats upsert error", e)

    return jsonify({"chatid": chat_id}), 200


# ==============================
# Database Functions
# ==============================
def get_all_posts():
    try:
        response = supabase.table("posts").select("*").order("created_at", desc=True).execute()
        posts = []
        for post in response.data or []:
            content_html = parse_markdown(post["content"])
            posts.append({
                "id": post["id"],
                "title": post["title"],
                "content": Markup(content_html),
                "slug": post["slug"],
                "date": datetime.fromisoformat(post["created_at"].replace("Z", "+00:00")).strftime("%b %d, %Y")
            })
        return posts
    except Exception as e:
        print(f"Error fetching posts: {e}")
        return []

def get_post_by_slug(slug):
    try:
        response = supabase.table("posts").select("*").eq("slug", slug).single().execute()
        post = response.data
        if not post:
            return None
        post["content_html"] = Markup(parse_markdown(post["content"]))
        post["date"] = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00")).strftime("%b %d, %Y")
        return post
    except Exception as e:
        print(f"Error fetching post: {e}")
        return None

# ==============================
# Routes: Blog
# ==============================
@app.route("/")
def index():
    posts = get_all_posts()
    return render_template("index.html", posts=posts)

@app.route("/write", methods=["GET", "POST"])
def write():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        if not title: return render_template("write.html", error="Title is required")
        if not content: return render_template("write.html", error="Content is required")
        slug = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        try:
            supabase.table("posts").insert({
                "title": title,
                "content": content,
                "slug": slug,
                "created_at": datetime.now(timezone.utc).isoformat()
            }).execute()
            return redirect("/")
        except Exception as e:
            return render_template("write.html", error=f"Failed to save: {e}")
    return render_template("write.html")

@app.route("/post/<slug>")
def view_post(slug):
    post = get_post_by_slug(slug)
    if not post:
        abort(404)
    return render_template("post.html", post=post)

@app.route("/delete/<slug>", methods=["POST"])
def delete_post(slug):
    try:
        supabase.table("posts").delete().eq("slug", slug).execute()
        return redirect("/")
    except Exception as e:
        return f"Error deleting: {e}", 500


# ==============================
# Main entry
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    # FIX: Disable debug mode in production
    is_debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=is_debug)


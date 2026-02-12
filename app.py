from flask import Flask, render_template, request, redirect, abort, session, url_for, jsonify
from markupsafe import Markup
from datetime import datetime, timezone, timedelta
import os
import re
import time
from supabase import create_client, Client
from datetime import datetime, timezone  # Add this import at the top
import uuid
# ==============================
# Supabase Configuration
# ==============================
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://zrckoammnhpjeoygnaec.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "YOUR_SUPABASE_KEY_HERE")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing Supabase environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==============================
# Flask App Config
# ==============================
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecretkey")
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

from flask import flash

@app.route('/auth', methods=['GET', 'POST'])
def auth():
    if request.method == 'POST':
        username = request.form.get("username")
        password = request.form.get("password")

        try:
            # Check if user already exists
            resp = supabase.table("profiles") \
                .select("id, name") \
                .eq("name", username) \
                .execute()

            if not resp.data or len(resp.data) == 0:
                # User does not exist → create new user
                # Use timezone-aware datetime
                new_user = supabase.table("profiles").insert({
                    "name": username,
                    "online": True,
                    "last_seen": datetime.now(timezone.utc).isoformat()
                }).execute()

                if not new_user.data or len(new_user.data) == 0:
                    return "Error creating user", 500

                user_id = new_user.data[0]['id']
            else:
                # User exists
                user_id = resp.data[0]['id']

            # ✅ Set session for current user
            session.clear()
            session['user'] = user_id
            session['username'] = username  # FIX: Store username for later use

            print(f"Logged in as {username}, session user ID set to {user_id}")
            return redirect("/quickchat")

        except Exception as e:
            print("Error during login/signup:", e)
            return f"Login/signup error: {str(e)}", 500  # Better error visibility

    # GET request → render login/signup form
    return render_template("auth.html")


@app.route('/api/chat/user')
def get_current_chat_user():
    user_id = session.get('user')
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401

    resp = supabase.table("profiles") \
        .select("id, name, online") \
        .eq("id", user_id) \
        .execute()

    if not resp.data:
        return jsonify({'error': 'Profile not found'}), 404

    user = resp.data[0]
    return jsonify({
        "id": user["id"],
        "username": user["name"],
        "online": user["online"]
    })


@app.route('/api/chat/users')
def get_chat_users():
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    current_id = session['user']
    print("Current user:", current_id)

    try:
        # Fetch all users except self
        resp = supabase.table("profiles") \
            .select("id, name, online") \
            .neq("id", current_id) \
            .execute()

        if resp.data is None:
            return jsonify({'error': 'Failed to fetch users'}), 500

        users = resp.data

        # Fetch pending requests TO current user
        try:
            requests_resp = supabase.table("chat_requests") \
                .select("from_user, status") \
                .eq("to_user", current_id) \
                .eq("status", "pending") \
                .execute()
            pending_requests = {r['from_user']: r for r in (requests_resp.data or [])}
        except Exception as e:
            pending_requests = {}

        # Fetch requests FROM current user
        try:
            sent_resp = supabase.table("chat_requests") \
                .select("to_user, status") \
                .eq("from_user", current_id) \
                .eq("status", "pending") \
                .execute()
            sent_requests = {r['to_user']: r for r in (sent_resp.data or [])}
        except Exception as e:
            sent_requests = {}

        # FIX: Fetch active chats with the ACTUAL chat_id
        try:
            active_resp = supabase.table("active_chats") \
                .select("*") \
                .contains("participants", [current_id]) \
                .eq("status", "active") \
                .execute()
            active_chats = active_resp.data or []
            print("Active chats found:", active_chats)
        except Exception as e:
            print("Error fetching active chats:", e)
            active_chats = []

        # Build lookup: other_user_id -> chat_id
        active_chat_map = {}  # {other_user_id: chat_id}
        for chat in active_chats:
            chat_id = chat['id']
            participants = chat.get('participants', [])
            for participant in participants:
                if participant != current_id:
                    active_chat_map[participant] = chat_id

        user_list = []
        for user in users:
            user_id = user['id']
            user_list.append({
                'id': user_id,
                'username': user['name'],
                'online': user['online'],
                'has_request': user_id in pending_requests,
                'request_sent': user_id in sent_requests,
                'chat_active': user_id in active_chat_map,
                'chat_id': active_chat_map.get(user_id)  # FIX: Include actual chat_id
            })

        print("User list with chat_ids:", user_list)
        return jsonify(user_list)

    except Exception as e:
        print("Error in get_chat_users:", e)
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat/request', methods=['POST'])
def send_chat_request():
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    from_user = session['user']
    to_user = data.get('user_id')

    if from_user == to_user:
        return jsonify({'error': 'Cannot request yourself'}), 400

    try:
        supabase.table("chat_requests").insert({
            "from_user": from_user,
            "to_user": to_user,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        return jsonify({'success': True})
    except Exception as e:
        print("Error sending request:", e)
        return jsonify({'error': str(e)}), 500


@app.route("/api/chat/messages/<chat_id>")
def api_chat_messages(chat_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    try:
        # FIX: Delete expired messages first (cleanup on every fetch)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
        try:
            supabase.table("messages") \
                .delete() \
                .lt("created_at", cutoff.isoformat()) \
                .execute()
        except Exception as e:
            print("Cleanup error (non-critical):", e)
        
        # Now fetch remaining messages
        resp = supabase.table("messages") \
            .select("*") \
            .eq("chat_id", chat_id) \
            .gt("created_at", cutoff.isoformat()) \
            .order("created_at", desc=False) \
            .execute()
            
        messages = resp.data or []
        
        # Calculate seconds_left
        for m in messages:
            try:
                created_str = m.get("created_at", "").replace('Z', '+00:00')
                created_time = datetime.fromisoformat(created_str)
                elapsed = (datetime.now(timezone.utc) - created_time).total_seconds()
                m["seconds_left"] = max(0, 30 - int(elapsed))
            except Exception as e:
                m["seconds_left"] = 0
                
        return jsonify(messages)
        
    except Exception as e:
        print("Error fetching messages:", e)
        return jsonify([]), 500

@app.route('/api/chat/request/accept', methods=['POST'])
def accept_chat_request():
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    from_user = data.get('user_id')
    to_user = session['user']

    try:
        # Update request to accepted
        supabase.table("chat_requests") \
            .update({"status": "accepted"}) \
            .eq("from_user", from_user) \
            .eq("to_user", to_user) \
            .eq("status", "pending") \
            .execute()

        # Create active chat with UUID
        chat_id = str(uuid.uuid4())
        supabase.table("active_chats").insert({
            "id": chat_id,
            "participants": [from_user, to_user],
            "status": "active",
            "started_at": datetime.now(timezone.utc).isoformat()
        }).execute()

        print(f"Chat created: {chat_id} between {from_user} and {to_user}")
        
        # Return the chat_id so frontend can use it
        return jsonify({
            'success': True,
            'chat_id': chat_id,
            'participants': [from_user, to_user]
        })
        
    except Exception as e:
        print("Error accepting request:", e)
        return jsonify({'error': str(e)}), 500


@app.route("/api/chat/send", methods=["POST"])
def api_chat_send():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    
    # DEBUG: Print what we received
    print(f"=== SEND MESSAGE DEBUG ===")
    print(f"Session user: {session.get('user')}")
    print(f"Request JSON: {data}")
    print(f"Headers: {dict(request.headers)}")
    
    chat_id = data.get("chat_id")
    text = data.get("text")
    
    if not chat_id:
        return jsonify({"error": "Missing chat_id"}), 400
    if not text:
        return jsonify({"error": "Missing text"}), 400

    try:
        message_data = {
            "chat_id": chat_id,  # This is the UUID string
            "sender": session["user"],
            "sender_name": session.get("username", "Anonymous"),
            "text": text,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        print(f"Inserting message: {message_data}")
        
        resp = supabase.table("messages").insert(message_data).execute()
        
        print(f"Supabase response: {resp}")
        
        if resp.data:
            message_data["id"] = resp.data[0]["id"]
            return jsonify(message_data)
        else:
            return jsonify({"error": "Insert failed, no data returned"}), 500
            
    except Exception as e:
        import traceback
        print("Error sending message:", traceback.format_exc())
        return jsonify({"error": str(e)}), 500
        
# =============================
# chat api
# =============================

# ==============================
# Markdown Parser
# ==============================
def parse_markdown(content):
    lines = content.split('\n')
    html_lines = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('# '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append(f'<h2>{stripped[2:].strip()}</h2>')
        elif stripped.startswith('## '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append(f'<h3>{stripped[3:].strip()}</h3>')
        elif stripped.startswith('### '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append(f'<h4>{stripped[4:].strip()}</h4>')
        elif stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list:
                html_lines.append('<ul>')
                in_list = True
            item = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', stripped[2:].strip())
            html_lines.append(f'<li>{item}</li>')
        elif stripped == '':
            if in_list:
                html_lines.append('</ul>')
                in_list = False
        else:
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', stripped)
            html_lines.append(f'<p>{text}</p>')

    if in_list:
        html_lines.append('</ul>')

    return ''.join(html_lines)

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
        print("Error fetching posts:", e)
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
        print("Error fetching post:", e)
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
        
@app.route("/api/chat/debug/send", methods=["POST"])
def debug_send():
    """Test endpoint to verify message insertion"""
    if "user" not in session:
        return jsonify({"error": "No session"}), 401
    
    data = request.json
    print("Session:", dict(session))
    print("Received data:", data)
    
    try:
        # Simple test insert
        test_msg = {
            "chat_id": data.get("chat_id", "test-chat-123"),
            "sender": session["user"],
            "sender_name": session.get("username", "test"),
            "text": data.get("text", "test message"),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        print("Inserting:", test_msg)
        
        resp = supabase.table("messages").insert(test_msg).execute()
        print("Supabase response:", resp)
        
        return jsonify({
            "success": True,
            "data": resp.data,
            "error": resp.error if hasattr(resp, 'error') else None
        })
    except Exception as e:
        import traceback
        print("Full error:", traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# ==============================
# Routes: Auth
# ==============================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        username = request.form.get("username")

        if not email or not password or not username:
            flash("All fields are required", "error")
            return redirect("/register")

        # Use Supabase auth to create user
        try:
            user_resp = supabase.auth.sign_up({
                "email": email,
                "password": password
            })

            user = user_resp.user
            if user:
                # 🔥 Ensure profile exists
                prof = supabase.table("profiles").select("*").eq("id", user.id).execute()

                if not prof.data:
                    supabase.table("profiles").insert({
                        "id": user.id,
                        "name": email.split("@")[0],
                        "online": True
                    }).execute()
                else:
                    supabase.table("profiles").update({
                        "online": True
                    }).eq("id", user.id).execute()

                session["user"] = user.id

                return redirect("/quickchat")


#            if user:
#                supabase.table("profiles").insert({
#                    "id": user.id,   # 🔥 MUST match auth user ID
#                    "name": username,
#                    "online": False
#                }).execute()
#
#
#                session["user"] = user.id
#                session["username"] = username
#                return redirect("/quickchat")
        except Exception as e:
            flash(f"Sign up error: {str(e)}", "error")
            return redirect("/register")

    return render_template("auth.html")  # your HTML page


from flask import Flask, render_template, request, redirect, session, flash, url_for
from datetime import datetime, timezone

# LOGIN ROUTE
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if not email or not password:
            flash("Email and password required", "error")
            return redirect(url_for('login'))

        try:
            # Supabase login
            user_resp = supabase.auth.sign_in_with_password({"email": email, "password": password})
            user = user_resp.user

            if user:
                # Fetch username from profiles table
                resp = supabase.table("profiles").select("username").eq("id", user.id).single().execute()
                username = resp.data["username"] if resp.data else "User"

                # Store session
                session["user"] = user.id
                session["username"] = username

                # Mark online in Supabase
                supabase.table("profiles").update({
                    "online": True,
                    "last_seen": datetime.now(timezone.utc).isoformat()
                }).eq("id", user.id).execute()

                return redirect("/quickchat")
            else:
                flash("Invalid login", "error")
                return redirect(url_for('login'))
        except Exception as e:
            flash(f"Login error: {str(e)}", "error")
            return redirect(url_for('login'))

    return render_template("auth.html")


# LOGOUT ROUTE
@app.route("/chat/logout")
def chat_logout():
    # Update Supabase online status if user is logged in
    if "user" in session:
        try:
            supabase.table("profiles").update({
                "online": False,
                "last_seen": datetime.now(timezone.utc).isoformat()
            }).eq("id", session["user"]).execute()
        except Exception as e:
            print("Logout error:", e)

    # Clear session
    session.clear()

    # Redirect to login page
    return redirect(url_for('login'))

    
# ==============================
# Routes: QuickChat
# ==============================
@app.route("/quickchat")
def quickchat():
    if "user" not in session:
        return redirect("/login")

    user_id = session["user"]
    print("SESSION USER ID:", user_id)


    # Update online status and last_seen
    try:
        supabase.table("profiles").update({
            "online": True,
            "last_seen": datetime.now(timezone.utc).isoformat()
        }).eq("id", user_id).execute()
    except Exception as e:
        print("Online update error:", e)

    # Fetch other online users
    try:
        resp = supabase.table("profiles").select("*").eq("online", True).neq("id", user_id).execute()
        users_data = resp.data or []
    except Exception as e:
        print("Fetch users error:", e)
        users_data = []

    # Pass current user info to template
    current_user = {
        "id": user_id,
        "username": session.get("username", "You")
    }

    return render_template("quickchat.html", users=users_data, current_user=current_user)


@app.route("/add-friend/<friend_id>")
def add_friend(friend_id):
    if "user" not in session:
        return redirect("/login")
    try:
        supabase.table("friends").insert({
            "user_id": session["user"],
            "friend_id": friend_id,
            "status": "pending"
        }).execute()
    except Exception as e:
        print("Add friend error:", e)
    return redirect("/quickchat")

# ==============================
# Main entry
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)


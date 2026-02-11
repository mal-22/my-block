from flask import Flask, render_template, request, redirect, Markup
from datetime import datetime
import os

app = Flask(__name__)

# Directory to store posts
POSTS_DIR = "posts"

# Ensure posts directory exists
if not os.path.exists(POSTS_DIR):
    os.makedirs(POSTS_DIR)

def read_post(filepath):
    """Read a Markdown post and return HTML"""
    with open(filepath, "r") as f:
        content = f.read()
    # Simple Markdown to HTML: convert # Title to <h1>
    lines = content.split("\n")
    html_lines = []
    for line in lines:
        if line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        else:
            html_lines.append(f"<p>{line}</p>")
    return "\n".join(html_lines)

@app.route("/")
def index():
    # Get list of posts, newest first
    post_files = sorted(os.listdir(POSTS_DIR), reverse=True)
    posts = []
    for filename in post_files:
        filepath = os.path.join(POSTS_DIR, filename)
        posts.append({
            "filename": filename,
            "content": Markup(read_post(filepath))
        })
    return render_template("index.html", posts=posts)

@app.route("/write", methods=["GET", "POST"])
def write():
    if request.method == "POST":
        title = request.form.get("title", "Untitled")
        content = request.form.get("content", "")
        # filename based on timestamp
        filename = datetime.now().strftime("%Y%m%d%H%M%S") + ".md"
        filepath = os.path.join(POSTS_DIR, filename)
        with open(filepath, "w") as f:
            f.write(f"# {title}\n\n{content}")
        return redirect("/")
    return render_template("write.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    # Cloud-safe host and port
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)

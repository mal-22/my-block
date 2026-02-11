from flask import Flask, render_template, request, redirect
from datetime import datetime
import os

app = Flask(__name__)
POSTS_DIR = "posts"

@app.route("/")
def index():
    posts = sorted(os.listdir(POSTS_DIR), reverse=True)
    return render_template("index.html", posts=posts)

@app.route("/write", methods=["GET", "POST"])
def write():
    if request.method == "POST":
        title = request.form["title"]
        content = request.form["content"]
        filename = datetime.now().strftime("%Y%m%d%H%M%S") + ".md"

        with open(os.path.join(POSTS_DIR, filename), "w") as f:
            f.write(f"# {title}\n\n{content}")

        return redirect("/")

    return render_template("write.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)

from flask import Flask, render_template, request, redirect, Markup
from datetime import datetime
import os
import re

app = Flask(__name__)

# Directory to store posts
POSTS_DIR = "posts"

# Ensure posts directory exists
if not os.path.exists(POSTS_DIR):
    os.makedirs(POSTS_DIR)

def parse_markdown(content):
    """Parse markdown content to HTML with better formatting"""
    lines = content.split('\n')
    html_lines = []
    in_list = False
    in_paragraph = False
    
    def close_paragraph():
        nonlocal in_paragraph
        if in_paragraph:
            html_lines.append('</p>')
            in_paragraph = False
    
    def close_list():
        nonlocal in_list
        if in_list:
            html_lines.append('</ul>')
            in_list = False
    
    for line in lines:
        stripped = line.strip()
        
        # Headers
        if stripped.startswith('# '):
            close_paragraph()
            close_list()
            title = stripped[2:].strip()
            html_lines.append(f'<h2>{title}</h2>')
        
        elif stripped.startswith('## '):
            close_paragraph()
            close_list()
            title = stripped[3:].strip()
            html_lines.append(f'<h3>{title}</h3>')
        
        elif stripped.startswith('### '):
            close_paragraph()
            close_list()
            title = stripped[4:].strip()
            html_lines.append(f'<h4>{title}</h4>')
        
        # List items
        elif stripped.startswith('- ') or stripped.startswith('* '):
            close_paragraph()
            if not in_list:
                html_lines.append('<ul>')
                in_list = True
            item_text = stripped[2:].strip()
            # Handle bold in list items
            item_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', item_text)
            html_lines.append(f'<li>{item_text}</li>')
        
        # Empty lines
        elif stripped == '':
            close_paragraph()
            close_list()
        
        # Regular paragraphs
        else:
            close_list()
            # Handle bold text **text**
            text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', stripped)
            # Handle italic *text*
            text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)
            
            if not in_paragraph:
                html_lines.append('<p>')
                in_paragraph = True
            else:
                html_lines.append(' ')
            html_lines.append(text)
    
    # Close any open tags
    close_paragraph()
    close_list()
    
    return ''.join(html_lines)

def read_post(filepath):
    """Read a Markdown post and return HTML"""
    try:
        with open(filepath, "r", encoding='utf-8') as f:
            content = f.read()
        return parse_markdown(content)
    except Exception as e:
        return f"<p>Error reading post: {str(e)}</p>"

def get_post_date(filename):
    """Extract date from filename (YYYYMMDDHHMMSS.md)"""
    try:
        date_str = filename.replace('.md', '')
        dt = datetime.strptime(date_str, "%Y%m%d%H%M%S")
        return dt.strftime("%b %d, %Y")
    except:
        return "Unknown date"

@app.route("/")
def index():
    # Get list of posts, newest first
    try:
        post_files = [f for f in os.listdir(POSTS_DIR) if f.endswith('.md')]
        post_files = sorted(post_files, reverse=True)
    except:
        post_files = []
    
    posts = []
    for filename in post_files:
        filepath = os.path.join(POSTS_DIR, filename)
        content = read_post(filepath)
        # Extract title from first h2 or use filename
        title_match = re.search(r'<h2>(.*?)</h2>', content)
        title = title_match.group(1) if title_match else "Untitled"
        
        posts.append({
            "filename": filename,
            "title": title,
            "date": get_post_date(filename),
            "content": Markup(content)
        })
    
    return render_template("index.html", posts=posts)

@app.route("/write", methods=["GET", "POST"])
def write():
    if request.method == "POST":
        title = request.form.get("title", "Untitled").strip()
        content = request.form.get("content", "").strip()
        
        if not content:
            return render_template("write.html", error="Content is required")
        
        # filename based on timestamp
        filename = datetime.now().strftime("%Y%m%d%H%M%S") + ".md"
        filepath = os.path.join(POSTS_DIR, filename)
        
        try:
            with open(filepath, "w", encoding='utf-8') as f:
                f.write(f"# {title}\n\n{content}")
            return redirect("/")
        except Exception as e:
            return render_template("write.html", error=f"Error saving post: {str(e)}")
    
    return render_template("write.html")

@app.route("/post/<filename>")
def view_post(filename):
    """View individual post"""
    filepath = os.path.join(POSTS_DIR, filename)
    if os.path.exists(filepath):
        content = read_post(filepath)
        date = get_post_date(filename)
        return render_template("post.html", content=Markup(content), date=date, filename=filename)
    return redirect("/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)

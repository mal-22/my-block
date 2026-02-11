from flask import Flask, render_template, request, redirect, abort
from markupsafe import Markup
from datetime import datetime
import os
import re
from supabase import create_client, Client

app = Flask(__name__)

# Supabase configuration
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def parse_markdown(content):
    """Parse markdown to HTML"""
    lines = content.split('\n')
    html_lines = []
    in_list = False
    
    for line in lines:
        stripped = line.strip()
        
        if stripped.startswith('# '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            title = stripped[2:].strip()
            html_lines.append(f'<h2>{title}</h2>')
        
        elif stripped.startswith('## '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            title = stripped[3:].strip()
            html_lines.append(f'<h3>{title}</h3>')
        
        elif stripped.startswith('### '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            title = stripped[4:].strip()
            html_lines.append(f'<h4>{title}</h4>')
        
        elif stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list:
                html_lines.append('<ul>')
                in_list = True
            item = stripped[2:].strip()
            item = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', item)
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

def get_all_posts():
    """Fetch all posts from Supabase"""
    try:
        response = supabase.table('posts').select('*').order('created_at', desc=True).execute()
        posts = []
        for post in response.data:
            content_html = parse_markdown(post['content'])
            posts.append({
                'id': post['id'],
                'title': post['title'],
                'content': Markup(content_html),
                'slug': post['slug'],
                'date': datetime.fromisoformat(post['created_at'].replace('Z', '+00:00')).strftime('%b %d, %Y')
            })
        return posts
    except Exception as e:
        print(f"Error fetching posts: {e}")
        return []

def get_post_by_slug(slug):
    """Fetch single post by slug"""
    try:
        response = supabase.table('posts').select('*').eq('slug', slug).execute()
        if response.data:
            post = response.data[0]
            post['content_html'] = Markup(parse_markdown(post['content']))
            post['date'] = datetime.fromisoformat(post['created_at'].replace('Z', '+00:00')).strftime('%b %d, %Y')
            return post
        return None
    except Exception as e:
        print(f"Error fetching post: {e}")
        return None

@app.route("/")
def index():
    posts = get_all_posts()
    return render_template("index.html", posts=posts)

@app.route("/write", methods=["GET", "POST"])
def write():
    if request.method == "POST":
        title = request.form.get("title", '').strip()
        content = request.form.get("content", '').strip()
        
        if not title:
            return render_template("write.html", error="Title is required")
        if not content:
            return render_template("write.html", error="Content is required")
        
        # Create unique slug from timestamp
        slug = datetime.now().strftime("%Y%m%d%H%M%S")
        
        try:
            # Insert into Supabase
            data = {
                'title': title,
                'content': content,
                'slug': slug
            }
            supabase.table('posts').insert(data).execute()
            
            return redirect("/")
        except Exception as e:
            return render_template("write.html", error=f"Failed to save: {str(e)}")
    
    return render_template("write.html")

@app.route("/post/<slug>")
def view_post(slug):
    """View individual post"""
    post = get_post_by_slug(slug)
    if not post:
        abort(404)
    return render_template("post.html", post=post)

@app.route("/delete/<slug>", methods=["POST"])
def delete_post(slug):
    """Delete a post (add auth later)"""
    try:
        supabase.table('posts').delete().eq('slug', slug).execute()
        return redirect("/")
    except Exception as e:
        return f"Error deleting: {e}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)

from flask import Flask, render_template, request, redirect, Markup, abort, url_for
from datetime import datetime
import os
import re
from supabase import create_client, Client

app = Flask(__name__)

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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
            html_lines.append(f'<h2>{stripped[2:]}</h2>')
        elif stripped.startswith('## '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append(f'<h3>{stripped[3:]}</h3>')
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
    try:
        response = supabase.table('posts').select('*').order('created_at', desc=True).execute()
        posts = []
        for post in response.data:
            posts.append({
                'id': post['id'],
                'title': post['title'],
                'content': Markup(parse_markdown(post['content'])),
                'slug': post['slug'],
                'date': datetime.fromisoformat(post['created_at'].replace('Z', '+00:00')).strftime('%b %d, %Y')
            })
        return posts
    except Exception as e:
        print(f"Error: {e}")
        return []

def get_post_by_slug(slug):
    try:
        response = supabase.table('posts').select('*').eq('slug', slug).execute()
        if response.data:
            post = response.data[0]
            post['content_html'] = Markup(parse_markdown(post['content']))
            post['date'] = datetime.fromisoformat(post['created_at'].replace('Z', '+00:00')).strftime('%b %d, %Y')
            return post
        return None
    except Exception as e:
        print(f"Error: {e}")
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
        
        if not title or not content:
            return render_template("write.html", error="Title and content required")
        
        slug = datetime.now().strftime("%Y%m%d%H%M%S")
        
        try:
            supabase.table('posts').insert({
                'title': title,
                'content': content,
                'slug': slug
            }).execute()
            return redirect("/")
        except Exception as e:
            return render_template("write.html", error=str(e))
    
    return render_template("write.html")

@app.route("/post/<slug>")
def view_post(slug):
    post = get_post_by_slug(slug)
    if not post:
        abort(404)
    return render_template("post.html", post=post)

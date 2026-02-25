"""Page routes (HTML)."""
from flask import render_template


def register_pages(app):
    @app.get("/")
    def home():
        return render_template("index.html")

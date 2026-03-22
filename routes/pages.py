"""Page routes (HTML)."""
from flask import render_template


def register_pages(app):
    @app.get("/")
    def home():
        return render_template("index.html", active_page="dashboard")

    @app.get("/settings")
    def settings():
        return render_template("settings.html", active_page="settings")

    @app.get("/pipeline-control")
    def pipeline_control():
        return render_template("pipeline_control.html", active_page="pipeline_control")

import os, io, uuid
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, send_file, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import LETTER

app = Flask(__name__)
app.secret_key = "change-me"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///cybercore.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_DIR"] = "uploads"
ADMIN_API_KEY = "change-me-admin-key"
os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

db = SQLAlchemy(app)

class Vendor(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    legal_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    vendor_type = db.Column(db.String(50))
    kybkyc = db.Column(db.Boolean, default=False)
    paid = db.Column(db.Boolean, default=False)
    score = db.Column(db.Integer, default=0)
    verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Document(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    vendor_id = db.Column(db.String(36))
    kind = db.Column(db.String(50), nullable=False)
    path = db.Column(db.String(500), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

def needed(): return {"insurance","license","w9","policy"}
def score_for(vendor_id):
    docs = Document.query.filter_by(vendor_id=vendor_id).all()
    kinds = {d.kind for d in docs}
    return int(100 * len(needed() & kinds)/len(needed()))

@app.route("/")
def index():
    return "✅ CyberCore Flask app is running — templates coming next!"

if __name__ == "__main__":
    app.run(port=5000, debug=True)


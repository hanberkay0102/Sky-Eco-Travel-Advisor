#!/usr/bin/env python3
"""
Simple HTTP server for the Sky frontend.
Run this instead of opening index.html directly.
Usage: python3 serve.py
Then open http://localhost:8080 in your browser.
"""
import http.server
import os

PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

os.chdir(DIRECTORY)

handler = http.server.SimpleHTTPRequestHandler
with http.server.HTTPServer(("", PORT), handler) as httpd:
    print(f"\n  Sky frontend running at: http://localhost:{PORT}")
    print(f"  Press Ctrl+C to stop.\n")
    httpd.serve_forever()

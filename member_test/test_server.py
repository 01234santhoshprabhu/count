from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
print("Member test dashboard: http://127.0.0.1:8786/")
ThreadingHTTPServer(("127.0.0.1", 8786), SimpleHTTPRequestHandler).serve_forever()


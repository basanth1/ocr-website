"""
run.py  —  start the OCR Pipeline Studio server
Usage:
    python run.py
    python run.py --port 8080
    python run.py --host 0.0.0.0 --port 5000 --no-debug
"""

import argparse
from app.main import app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OCR Pipeline Studio")
    parser.add_argument("--host",     default="127.0.0.1")
    parser.add_argument("--port",     default=5000, type=int)
    parser.add_argument("--no-debug", dest="debug", action="store_false")
    parser.set_defaults(debug=True)
    args = parser.parse_args()

    print(f"\n  ✦  OCR Pipeline Studio")
    print(f"  →  http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)

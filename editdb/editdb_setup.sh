#!/usr/bin/env zsh

# EditDB Setup Script
# This script prepares the environment for the EditDB Local Web App.

set -e

print "🚀 Starting EditDB setup..."

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    print "❌ Error: python3 is not installed."
    exit 1
fi

# Create a virtual environment to avoid Homebrew/PEP 668 conflicts
if [ ! -d ".venv" ]; then
    print "🌐 Creating virtual environment (.venv)..."
    python3 -m venv .venv
fi

print "📦 Installing Python dependencies into .venv..."
# python-multipart is required by FastAPI for form/file handling
./.venv/bin/python3 -m pip install --upgrade pip
./.venv/bin/python3 -m pip install fastapi uvicorn python-multipart

print "✅ Dependencies installed successfully!"
print "🛠️  Making src/editdb.py executable..."
chmod +x src/editdb.py

print "\n🎉 Setup complete! To run EditDB:"
print "   ./.venv/bin/python3 src/editdb.py path/to/your/database.sqlite"
print "\nAlternative (if you want to use your system python and it allows it):"
print "   python3 -m pip install fastapi uvicorn python-multipart"

import sys
import os

# Add Backend to path
sys.path.append(os.path.join(os.getcwd(), 'Backend'))

try:
    print("Attempting to import Backend.main...")
    import main
    print("Successfully imported Backend.main")
except Exception as e:
    print(f"Error importing Backend.main: {e}")
    import traceback
    traceback.print_exc()

try:
    import uvicorn
    print("uvicorn is installed")
except ImportError:
    print("uvicorn is NOT installed")

try:
    import streamlit
    print("streamlit is installed")
except ImportError:
    print("streamlit is NOT installed")

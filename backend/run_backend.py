import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock pytesseract first (since Tesseract is not installed)
class MockPytesseract:
    @staticmethod
    def image_to_string(image, **kwargs):
        return ""  # Empty string for OCR

sys.modules['pytesseract'] = MockPytesseract()

print("Starting Skill Mapping Platform Backend...")
print("=" * 50)

try:
    from app.main import app
    print("[OK] App imported successfully")
    
    import uvicorn
    print("\\n" + "=" * 50)
    print("Backend Server Starting!")
    print("=" * 50)
    print(f"URL: http://localhost:8000")
    print(f"API Docs: http://localhost:8000/docs")
    print(f"Admin: http://localhost:8000/redoc")
    print("\\nDemo Credentials:")
    print("  Manager: manager@example.com / password123")
    print("  Developer: abdul.moeed@example.com / password123")
    print("\\nPress Ctrl+C to stop the server")
    print("=" * 50 + "\\n")
    
    # Use import string so --reload works (reload spawns a child process that re-imports the app).
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
    
except Exception as e:
    print(f"\\n[ERROR] Error starting server: {e}")
    import traceback
    traceback.print_exc()
    input("\\nPress Enter to exit...")

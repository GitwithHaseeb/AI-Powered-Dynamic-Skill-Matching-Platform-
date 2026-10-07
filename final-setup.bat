# Create the setup file
@'
@echo off
echo ===========================================
echo   FINAL SETUP - Skill Mapping Platform
echo ===========================================
echo.

echo [INFO] Checking Docker...
docker --version
if %errorlevel% neq 0 (
    echo [ERROR] Docker not running. Please start Docker Desktop.
    pause
    exit /b 1
)

echo [SUCCESS] Docker is ready!
echo.

echo [1/6] Setting up Python Backend...
cd backend

REM Create virtual environment
if not exist venv (
    echo Creating Python virtual environment...
    python -m venv venv
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing Python dependencies...
pip install --upgrade pip

REM Create requirements file
(
echo fastapi==0.104.1
echo uvicorn[standard]==0.24.0
echo pydantic==2.5.0
echo pymongo==4.6.0
echo python-jose[cryptography]==3.3.0
echo passlib[bcrypt]==1.7.4
echo python-dotenv==1.0.0
echo python-multipart==0.0.6
echo cors==1.0.1
echo python-docx==1.1.0
echo Pillow==10.1.0
echo nltk==3.8.1
) > requirements.txt

pip install -r requirements.txt

echo Creating uploads directory...
mkdir uploads\srs_documents uploads\temp 2>nul

echo Creating configuration files...

REM Create .env file
(
echo # App Configuration
echo DEBUG=True
echo HOST=0.0.0.0
echo PORT=8000
echo.
echo # MongoDB Docker
echo MONGODB_URL=mongodb://admin:password123@localhost:27017/skill_mapping?authSource=admin
echo MONGODB_DB_NAME=skill_mapping
echo.
echo # JWT
echo SECRET_KEY=dev-secret-key-123456-change-in-production
echo ACCESS_TOKEN_EXPIRE_MINUTES=10080
echo.
echo # File Uploads
echo UPLOAD_DIR=./uploads
echo MAX_FILE_SIZE=10485760
) > .env

cd ..
echo [SUCCESS] Backend setup complete!
echo.

echo [2/6] Creating MongoDB Docker configuration...
cd backend

REM Create docker-compose.yml
(
echo version: '3.8'
echo.
echo services:
echo   mongodb:
echo     image: mongo:latest
echo     container_name: skill_mapping_mongodb
echo     restart: always
echo     ports:
echo       - "27017:27017"
echo     environment:
echo       MONGO_INITDB_ROOT_USERNAME: admin
echo       MONGO_INITDB_ROOT_PASSWORD: password123
echo       MONGO_INITDB_DATABASE: skill_mapping
echo     volumes:
echo       - mongodb_data:/data/db
echo.
echo volumes:
echo   mongodb_data:
) > docker-compose.yml

echo [SUCCESS] Docker configuration created!
echo.

echo [3/6] Starting MongoDB with Docker...
echo Starting MongoDB container...
docker-compose up -d mongodb

echo Waiting for MongoDB to start...
timeout /t 10 /nobreak >nul

echo Checking MongoDB status...
docker ps | findstr mongodb
if %errorlevel% neq 0 (
    echo [WARNING] MongoDB container not running. Trying to start...
    docker-compose restart mongodb
    timeout /t 5 /nobreak >nul
)

echo [SUCCESS] MongoDB should be running!
echo.

echo [4/6] Initializing MongoDB with sample data...
echo Creating initialization script...

(
echo import pymongo
echo import datetime
echo from passlib.hash import bcrypt
echo.
echo # Connect to MongoDB
echo client = pymongo.MongoClient("mongodb://admin:password123@localhost:27017/skill_mapping?authSource=admin")
echo db = client["skill_mapping"]
echo.
echo # Create collections if they don't exist
echo collections = ["users", "projects", "tasks", "skills", "srs_documents"]
echo for collection in collections:
echo     if collection not in db.list_collection_names():
echo         db.create_collection(collection)
echo         print(f"Created collection: {collection}")
echo.
echo # Hash password
echo def hash_password(password):
echo     return bcrypt.hash(password)
echo.
echo # Sample users
echo users = [
echo     {
echo         "name": "MUHAMMAD HASEEB",
echo         "email": "muhammad.haseeb@example.com",
echo         "role": "developer",
echo         "department": "Computer Science",
echo         "cgpa": 2.97,
echo         "contact": "0313-4377476",
echo         "availability": True,
echo         "skills": ["React", "Material-UI", "JavaScript", "CSS", "HTML"],
echo         "experience_years": 1.5,
echo         "current_workload": 1,
echo         "performance_history": [4.2, 4.0, 4.3],
echo         "hashed_password": hash_password("password123"),
echo         "created_at": datetime.datetime.utcnow(),
echo         "updated_at": datetime.datetime.utcnow()
echo     },
echo     {
echo         "name": "GHANIA TANVEER",
echo         "email": "ghania.tanveer@example.com",
echo         "role": "developer",
echo         "department": "Computer Science",
echo         "cgpa": 2.25,
echo         "contact": "0320-1471189",
echo         "availability": True,
echo         "skills": ["Python", "Scikit-learn", "TensorFlow", "Pandas", "NLP"],
echo         "experience_years": 1,
echo         "current_workload": 0,
echo         "performance_history": [4.0, 3.8, 4.1],
echo         "hashed_password": hash_password("password123"),
echo         "created_at": datetime.datetime.utcnow(),
echo         "updated_at": datetime.datetime.utcnow()
echo     },
echo     {
echo         "name": "Project Manager",
echo         "email": "manager@example.com",
echo         "role": "manager",
echo         "department": "Management",
echo         "availability": True,
echo         "hashed_password": hash_password("password123"),
echo         "created_at": datetime.datetime.utcnow(),
echo         "updated_at": datetime.datetime.utcnow()
echo     }
echo ]
echo.
echo # Clear and insert users
echo db.users.delete_many({})
echo result = db.users.insert_many(users)
echo print(f"✓ Inserted {len(result.inserted_ids)} users")
echo print("✓ MongoDB initialized successfully!")
echo print()
echo print("Demo accounts created:")
echo print("  Manager: manager@example.com / password123")
echo print("  Developer: muhammad.haseeb@example.com / password123")
echo print("  Developer: ghania.tanveer@example.com / password123")
) > init_mongodb.py

echo Running MongoDB initialization...
python init_mongodb.py

cd ..
echo [SUCCESS] MongoDB initialized!
echo.

echo [5/6] Setting up Frontend...
cd frontend

echo Installing Node.js dependencies...
npm install

echo Creating frontend environment file...
(
echo REACT_APP_API_URL=http://localhost:8000
echo REACT_APP_ENV=development
) > .env

cd ..
echo [SUCCESS] Frontend setup complete!
echo.

echo [6/6] Creating startup scripts...
(
echo @echo off
echo echo ===========================================
echo echo   Starting Skill Mapping Platform Backend
echo echo ===========================================
echo echo.
echo cd /d "%~dp0backend"
echo call venv\Scripts\activate.bat
echo uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
) > start-backend.bat

(
echo @echo off
echo echo ===========================================
echo echo   Starting Skill Mapping Platform Frontend
echo echo ===========================================
echo echo.
echo cd /d "%~dp0frontend"
echo npm start
) > start-frontend.bat

(
echo @echo off
echo echo ===========================================
echo echo   Docker Status Check
echo echo ===========================================
echo echo.
echo echo Docker Containers:
echo docker ps
echo echo.
echo echo MongoDB Logs:
echo docker-compose -f backend\docker-compose.yml logs mongodb --tail=10
echo echo.
echo echo To stop MongoDB:
echo echo docker-compose -f backend\docker-compose.yml down
echo echo.
echo echo To restart MongoDB:
echo echo docker-compose -f backend\docker-compose.yml restart mongodb
) > docker-status.bat

echo ===========================================
echo SETUP COMPLETED SUCCESSFULLY! 🎉
echo ===========================================
echo.
echo To start the application:
echo.
echo 1. Make sure Docker Desktop is running
echo 2. Start Backend Server:
echo    - Double-click: start-backend.bat
echo    - OR: cd backend ^&^& venv\Scripts\activate ^&^& uvicorn app.main:app --reload
echo.
echo 3. Start Frontend Server (NEW TERMINAL):
echo    - Double-click: start-frontend.bat
echo    - OR: cd frontend ^&^& npm start
echo.
echo 4. Access the application:
echo    - Frontend: http://localhost:3000
echo    - Backend API: http://localhost:8000
echo    - API Documentation: http://localhost:8000/docs
echo.
echo 5. Check Docker status:
echo    - Double-click: docker-status.bat
echo.
echo Demo Accounts (use any):
echo    Manager: manager@example.com / password123
echo    Developer: muhammad.haseeb@example.com / password123
echo    Developer: ghania.tanveer@example.com / password123
echo.
echo Troubleshooting:
echo    - If backend fails: Check MongoDB is running with docker-status.bat
echo    - Restart MongoDB: cd backend ^&^& docker-compose restart mongodb
echo    - View logs: cd backend ^&^& docker-compose logs mongodb
echo.
pause
'@ | Out-File -FilePath final-setup.bat -Encoding ASCII
@echo off
echo ===========================================
echo   Skill Mapping Platform - Docker Setup
echo ===========================================
echo.

echo Checking Docker installation...
docker --version
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not installed or not running.
    echo Please make sure Docker Desktop is running.
    pause
    exit /b 1
)

echo Docker is installed and running!
echo.

echo [1/5] Setting up Python Backend...
cd backend

REM Create virtual environment
if not exist venv (
    echo Creating Python virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing Python dependencies...
pip install --upgrade pip

REM Create minimal requirements
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
echo spacy==3.7.2
) > requirements-minimal.txt

pip install -r requirements-minimal.txt

REM Download spaCy model
echo Downloading spaCy model...
python -m spacy download en_core_web_sm

REM Create uploads directory
if not exist uploads\srs_documents mkdir uploads\srs_documents
if not exist uploads\temp mkdir uploads\temp

REM Create .env file
echo Creating environment configuration...
(
echo # App Configuration
echo DEBUG=True
echo APP_NAME="Skill Mapping Platform"
echo APP_VERSION="1.0.0"
echo.
echo # Server
echo HOST=0.0.0.0
echo PORT=8000
echo.
echo # MongoDB Docker
echo MONGODB_URL=mongodb://admin:password123@localhost:27017/skill_mapping?authSource=admin
echo MONGODB_DB_NAME=skill_mapping
echo.
echo # JWT
echo SECRET_KEY=your-secret-key-for-development-123
echo ACCESS_TOKEN_EXPIRE_MINUTES=1440
echo.
echo # ML
echo ML_MODEL_PATH=./app/ml/model.pkl
echo SPACY_MODEL=en_core_web_sm
echo SENTENCE_MODEL=all-MiniLM-L6-v2
echo.
echo # File Uploads
echo UPLOAD_DIR=./uploads
echo MAX_FILE_SIZE=10485760
) > .env

cd ..
echo Backend Python setup complete!
echo.

echo [2/5] Creating MongoDB initialization file...
cd backend

REM Create mongo-init.js
(
echo // MongoDB initialization script
echo db = db.getSiblingDB('skill_mapping');
echo.
echo // Create collections
echo db.createCollection('users');
echo db.createCollection('projects');
echo db.createCollection('tasks');
echo db.createCollection('skills');
echo db.createCollection('srs_documents');
echo.
echo // Insert sample users
echo db.users.insertMany([
echo   {
echo     name: "ABDUL MOEED",
echo     email: "abdul.moeed@example.com",
echo     role: "developer",
echo     department: "Computer Science",
echo     cgpa: 3.0,
echo     contact: "0320-1406301",
echo     availability: true,
echo     skills: ["React", "Node.js", "MongoDB", "Python", "AI/ML", "JavaScript", "Express.js"],
echo     experience_years: 2,
echo     current_workload: 2,
echo     performance_history: [4.5, 4.3, 4.7],
echo     hashed_password: "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW", // password123
echo     created_at: new Date(),
echo     updated_at: new Date()
echo   },
echo   {
echo     name: "MUHAMMAD HASEEB",
echo     email: "muhammad.haseeb@example.com",
echo     role: "developer",
echo     department: "Computer Science",
echo     cgpa: 2.97,
echo     contact: "0313-4377476",
echo     availability: true,
echo     skills: ["React", "Material-UI", "JavaScript", "CSS", "HTML", "Redux", "TypeScript"],
echo     experience_years: 1.5,
echo     current_workload: 1,
echo     performance_history: [4.2, 4.0, 4.3],
echo     hashed_password: "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
echo     created_at: new Date(),
echo     updated_at: new Date()
echo   },
echo   {
echo     name: "GHANIA TANVEER",
echo     email: "ghania.tanveer@example.com",
echo     role: "developer",
echo     department: "Computer Science",
echo     cgpa: 2.25,
echo     contact: "0320-1471189",
echo     availability: true,
echo     skills: ["Python", "Scikit-learn", "TensorFlow", "Pandas", "NLP", "Machine Learning", "Deep Learning"],
echo     experience_years: 1,
echo     current_workload: 0,
echo     performance_history: [4.0, 3.8, 4.1],
echo     hashed_password: "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
echo     created_at: new Date(),
echo     updated_at: new Date()
echo   },
echo   {
echo     name: "Project Manager",
echo     email: "manager@example.com",
echo     role: "manager",
echo     department: "Management",
echo     availability: true,
echo     hashed_password: "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
echo     created_at: new Date(),
echo     updated_at: new Date()
echo   }
echo ]);
echo.
echo print("MongoDB initialized with sample data!");
) > mongo-init.js

cd ..
echo MongoDB initialization file created!
echo.

echo [3/5] Starting MongoDB with Docker...
cd backend

echo Starting MongoDB container...
docker-compose up -d mongodb

echo Waiting for MongoDB to start...
timeout /t 15 /nobreak >nul

echo Initializing MongoDB with sample data...
docker-compose exec -T mongodb mongosh --username admin --password password123 --authenticationDatabase admin skill_mapping < mongo-init.js

cd ..
echo MongoDB setup complete!
echo.

echo [4/5] Setting up Node.js Frontend...
cd frontend

REM Install dependencies
echo Installing Node.js dependencies...
npm install

REM Create .env file
echo Creating frontend environment file...
(
echo REACT_APP_API_URL=http://localhost:8000
echo REACT_APP_ENV=development
) > .env

cd ..
echo Frontend setup complete!
echo.

echo [5/5] Creating startup scripts...
echo Creating start-backend.bat...
(
echo @echo off
echo cd /d "%~dp0backend"
echo call venv\Scripts\activate.bat
echo uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
) > start-backend.bat

echo Creating start-frontend.bat...
(
echo @echo off
echo cd /d "%~dp0frontend"
echo npm start
) > start-frontend.bat

echo Creating docker-status.bat...
(
echo @echo off
echo echo Checking Docker containers...
echo docker ps
echo echo.
echo echo If MongoDB is not running, start it with:
echo echo cd backend ^&^& docker-compose up -d mongodb
) > docker-status.bat

echo ===========================================
echo DOCKER SETUP COMPLETED SUCCESSFULLY!
echo ===========================================
echo.
echo Next steps:
echo.
echo 1. Start Backend Server:
echo    - Double-click: start-backend.bat
echo    - OR: cd backend ^&^& venv\Scripts\activate ^&^& uvicorn app.main:app --reload
echo.
echo 2. Start Frontend Server (in new terminal):
echo    - Double-click: start-frontend.bat
echo    - OR: cd frontend ^&^& npm start
echo.
echo 3. Access the application:
echo    - Frontend: http://localhost:3000
echo    - Backend API: http://localhost:8000
echo    - API Docs: http://localhost:8000/docs
echo.
echo 4. Check Docker status:
echo    - Double-click: docker-status.bat
echo.
echo Demo Accounts:
echo    Manager: manager@example.com / password123
echo    Developer: abdul.moeed@example.com / password123
echo    Developer: muhammad.haseeb@example.com / password123
echo    Developer: ghania.tanveer@example.com / password123
echo.
echo Troubleshooting:
echo    - If MongoDB fails: cd backend ^&^& docker-compose logs mongodb
echo    - Restart MongoDB: cd backend ^&^& docker-compose restart mongodb
echo.
pause

@echo off
echo ===========================================
echo   Skill Mapping Platform Setup Script
echo ===========================================
echo.

REM Check current directory
echo Current directory: %cd%
echo.

REM Step 1: Setup Backend
echo [1/4] Setting up Backend...
cd backend

REM Create virtual environment
if not exist venv (
    echo Creating Python virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install Python dependencies
echo Installing Python dependencies...
pip install --upgrade pip
pip install -r requirements.txt

REM Download spaCy model
echo Downloading spaCy model...
python -m spacy download en_core_web_sm

REM Create uploads directory
if not exist uploads\srs_documents mkdir uploads\srs_documents
if not exist uploads\temp mkdir uploads\temp

REM Start MongoDB
echo Starting MongoDB...
docker-compose up -d mongodb

REM Wait for MongoDB to start
echo Waiting for MongoDB to start (10 seconds)...
timeout /t 10 /nobreak >nul

REM Initialize MongoDB
echo Initializing MongoDB with sample data...
docker-compose exec -T mongodb mongosh --username admin --password password123 --authenticationDatabase admin skill_mapping < mongo-init.js

cd ..
echo Backend setup complete!
echo.

REM Step 2: Setup Frontend
echo [2/4] Setting up Frontend...
cd frontend

REM Install Node.js dependencies
echo Installing Node.js dependencies...
npm install

REM Create .env file
echo Creating environment file...
echo REACT_APP_API_URL=http://localhost:8000 > .env
echo REACT_APP_ENV=development >> .env

cd ..
echo Frontend setup complete!
echo.

echo ===========================================
echo Setup completed successfully!
echo ===========================================
echo.
echo To start the application:
echo.
echo 1. Start backend (new terminal):
echo    cd backend
echo    venv\Scripts\activate
echo    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
echo.
echo 2. Start frontend (new terminal):
echo    cd frontend
echo    npm start
echo.
echo 3. Access at:
echo    - Frontend: http://localhost:3000
echo    - Backend API: http://localhost:8000
echo    - API Docs: http://localhost:8000/docs
echo.
echo Demo accounts:
echo    Manager: manager@example.com / password123
echo    Developer: muhammad.haseeb@example.com / password123
echo.
pause
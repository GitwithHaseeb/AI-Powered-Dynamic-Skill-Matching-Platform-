#!/bin/bash
# Lives in scripts/ — run everything from the repo root.
cd "$(dirname "$0")/.." || exit 1

echo "Setting up Skill Mapping Platform..."

# Backend setup
echo "Setting up backend..."
cd backend

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Download spaCy model
python -m spacy download en_core_web_sm

# Create uploads directory
mkdir -p uploads/srs_documents uploads/temp

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env file. Please update with your configuration."
fi

# Start MongoDB (requires Docker)
echo "Starting MongoDB with Docker..."
docker-compose up -d mongodb

# Wait for MongoDB to start
sleep 5

# Initialize MongoDB with sample data
echo "Initializing MongoDB..."
docker-compose exec -T mongodb mongosh < mongo-init.js

echo "Backend setup complete!"

# Frontend setup
echo "Setting up frontend..."
cd ../frontend

# Install dependencies
npm install

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "REACT_APP_API_URL=http://localhost:8000" > .env
fi

echo "Frontend setup complete!"

echo ""
echo "Setup completed successfully!"
echo ""
echo "To start the application:"
echo "1. Backend: cd backend && uvicorn app.main:app --reload"
echo "2. Frontend: cd frontend && npm start"
echo ""
echo "Access the application at:"
echo "- Frontend: http://localhost:3000"
echo "- Backend API: http://localhost:8000"
echo "- API Docs: http://localhost:8000/docs"
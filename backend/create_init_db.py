import pymongo
import json
from datetime import datetime

print("Connecting to MongoDB...")

# Connect to MongoDB
try:
    client = pymongo.MongoClient("mongodb://localhost:27017")
    db = client["skill_mapping"]
    print("✓ Connected to MongoDB")
except Exception as e:
    print(f"✗ MongoDB connection failed: {e}")
    exit(1)

# Clear existing collections (optional)
collections = ["users", "projects", "tasks", "skills", "srs_documents"]
for collection in collections:
    try:
        db[collection].drop()
        print(f"✓ Cleared {collection} collection")
    except:
        print(f"  {collection} collection didn't exist or couldn't be cleared")

# Create sample users
sample_users = [
    {
        "_id": "1",
        "name": "ABDUL MOEED",
        "email": "abdul.moeed@example.com",
        "username": "abdulmoeed",
        "role": "developer",
        "department": "Computer Science",
        "cgpa": 3.0,
        "contact": "0320-1406301",
        "availability": True,
        "skills": ["React", "Node.js", "MongoDB", "Python", "AI/ML", "JavaScript", "Express.js"],
        "experience_years": 2,
        "current_workload": 2,
        "performance_history": [4.5, 4.3, 4.7],
        "hashed_password": "",  # password123
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    },
    {
        "_id": "2",
        "name": "MUHAMMAD HASEEB",
        "email": "muhammad.haseeb@example.com",
        "username": "mhaseeb",
        "role": "developer",
        "department": "Computer Science",
        "cgpa": 2.97,
        "contact": "0313-4377476",
        "availability": True,
        "skills": ["React", "Material-UI", "JavaScript", "CSS", "HTML", "Redux", "TypeScript"],
        "experience_years": 1.5,
        "current_workload": 1,
        "performance_history": [4.2, 4.0, 4.3],
        "hashed_password": "",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    },
    {
        "_id": "3",
        "name": "GHANIA TANVEER",
        "email": "ghania.tanveer@example.com",
        "username": "ghaniatanveer",
        "role": "developer",
        "department": "Computer Science",
        "cgpa": 2.25,
        "contact": "0320-1471189",
        "availability": True,
        "skills": ["Python", "Scikit-learn", "TensorFlow", "Pandas", "NLP", "Machine Learning", "Deep Learning"],
        "experience_years": 1,
        "current_workload": 0,
        "performance_history": [4.0, 3.8, 4.1],
        "hashed_password": "",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    },
    {
        "_id": "4",
        "name": "Project Manager",
        "email": "manager@example.com",
        "username": "manager",
        "role": "manager",
        "department": "Management",
        "availability": True,
        "hashed_password": "",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
]

# Insert users
try:
    result = db.users.insert_many(sample_users)
    print(f"✓ Inserted {len(result.inserted_ids)} users")
except Exception as e:
    print(f"✗ Error inserting users: {e}")

print("\\n" + "=" * 50)
print("Database Initialization Complete!")
print("=" * 50)
print("Users created:")
for user in sample_users:
    print(f"  • {user['name']} ({user['email']}) - {user['role']}")
print("\\nYou can now run the backend server.")
print("Use: python run_backend.py")

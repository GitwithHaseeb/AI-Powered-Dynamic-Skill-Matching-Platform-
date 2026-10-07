// Initialize MongoDB with sample data
db = db.getSiblingDB('skill_mapping');

// Create collections
db.createCollection('users');
db.createCollection('projects');
db.createCollection('tasks');
db.createCollection('skills');
db.createCollection('srs_documents');

// Create indexes
db.users.createIndex({ email: 1 }, { unique: true });
db.users.createIndex({ role: 1 });
db.users.createIndex({ availability: 1 });

db.projects.createIndex({ created_by: 1 });
db.projects.createIndex({ status: 1 });
db.projects.createIndex({ deadline: 1 });

db.tasks.createIndex({ assigned_to: 1 });
db.tasks.createIndex({ project_id: 1 });
db.tasks.createIndex({ status: 1 });

// Insert sample users
db.users.insertMany([
  {
    name: "MUHAMMAD HASEEB",
    email: "muhammad.haseeb@example.com",
    role: "developer",
    department: "Computer Science",
    cgpa: 2.97,
    contact: "0313-4377476",
    availability: true,
    skills: ["React", "Material-UI", "JavaScript", "CSS", "HTML", "Redux", "TypeScript"],
    experience_years: 1.5,
    current_workload: 1,
    performance_history: [4.2, 4.0, 4.3],
    hashed_password: "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    name: "GHANIA TANVEER",
    email: "ghania.tanveer@example.com",
    role: "developer",
    department: "Computer Science",
    cgpa: 2.25,
    contact: "0320-1471189",
    availability: true,
    skills: ["Python", "Scikit-learn", "TensorFlow", "Pandas", "NLP", "Machine Learning", "Deep Learning"],
    experience_years: 1,
    current_workload: 0,
    performance_history: [4.0, 3.8, 4.1],
    hashed_password: "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    name: "Project Manager",
    email: "manager@example.com",
    role: "manager",
    department: "Management",
    availability: true,
    hashed_password: "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
    created_at: new Date(),
    updated_at: new Date()
  }
]);

print("Database initialized with sample data");
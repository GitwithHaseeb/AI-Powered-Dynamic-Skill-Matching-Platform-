import spacy
from sklearn.feature_extraction.text import TfidfVectorizer
import joblib
import numpy as np

class SkillExtractor:
    def __init__(self):
        self.nlp = spacy.load("en_core_web_sm")
        self.vectorizer = TfidfVectorizer(max_features=1000)
        self.skill_keywords = [
            # Programming Languages
            'python', 'javascript', 'java', 'c++', 'c#', 'php', 'ruby', 'swift', 'kotlin',
            'typescript', 'go', 'rust', 'scala', 'perl', 'r', 'matlab',
            
            # Frontend
            'react', 'angular', 'vue', 'next.js', 'nuxt.js', 'svelte', 'jquery',
            'html', 'css', 'sass', 'less', 'bootstrap', 'tailwind', 'material-ui',
            
            # Backend
            'node.js', 'django', 'flask', 'fastapi', 'spring', 'express.js', 'laravel',
            'asp.net', 'ruby on rails', 'graphql', 'rest api', 'microservices',
            
            # Database
            'mongodb', 'mysql', 'postgresql', 'sqlite', 'oracle', 'sql server',
            'redis', 'elasticsearch', 'cassandra', 'dynamodb', 'firebase',
            
            # DevOps
            'docker', 'kubernetes', 'aws', 'azure', 'gcp', 'jenkins', 'gitlab',
            'github actions', 'terraform', 'ansible', 'prometheus', 'grafana',
            
            # ML/AI
            'tensorflow', 'pytorch', 'scikit-learn', 'keras', 'opencv', 'nltk',
            'spacy', 'pandas', 'numpy', 'matplotlib', 'seaborn', 'huggingface',
            
            # Mobile
            'react native', 'flutter', 'android', 'ios', 'xamarin', 'ionic',
            
            # Tools
            'git', 'jira', 'confluence', 'slack', 'figma', 'adobe xd', 'postman',
            'swagger', 'linux', 'bash', 'powershell'
        ]
    
    def extract_skills_from_text(self, text: str) -> list:
        """Extract technical skills from text"""
        text_lower = text.lower()
        found_skills = []
        
        # Check for exact matches
        for skill in self.skill_keywords:
            if skill in text_lower:
                found_skills.append(skill)
        
        # Use NLP to find skill mentions
        doc = self.nlp(text)
        
        # Look for skills in noun phrases
        for chunk in doc.noun_chunks:
            chunk_text = chunk.text.lower()
            for skill in self.skill_keywords:
                if skill in chunk_text and skill not in found_skills:
                    found_skills.append(skill)
        
        return list(set(found_skills))
    
    def calculate_skill_importance(self, text: str, skills: list) -> dict:
        """Calculate importance score for each skill in context"""
        # Simple frequency-based importance
        text_lower = text.lower()
        importance_scores = {}
        
        for skill in skills:
            # Count occurrences
            count = text_lower.count(skill)
            # Weight by skill position (skills mentioned earlier might be more important)
            position = text_lower.find(skill)
            position_score = 1.0 if position == -1 else max(0.1, 1 - (position / len(text_lower)))
            
            importance_scores[skill] = count * position_score
        
        # Normalize scores
        max_score = max(importance_scores.values()) if importance_scores else 1
        for skill in importance_scores:
            importance_scores[skill] = importance_scores[skill] / max_score
        
        return importance_scores
    
    def train(self, documents: list, labels: list = None):
        """Train the skill extractor model"""
        # This is a simplified version - you'd want to train on labeled data
        print("Skill extractor trained on sample data")
    
    def save_model(self, path: str):
        """Save the trained model"""
        model_data = {
            'skill_keywords': self.skill_keywords,
            'vectorizer': self.vectorizer
        }
        joblib.dump(model_data, path)
    
    def load_model(self, path: str):
        """Load a trained model"""
        model_data = joblib.load(path)
        self.skill_keywords = model_data['skill_keywords']
        self.vectorizer = model_data['vectorizer']
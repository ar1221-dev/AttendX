import os
import sys

# Ensure parent directory is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set DATABASE_URL to Supabase Pooler
os.environ['DATABASE_URL'] = "postgresql://postgres.qzbddlqoopizaweiwbxt:thisIsRaj@12345@aws-1-ap-south-1.pooler.supabase.com:6543/postgres"

from app import app
import db_engine

def main():
    print("Initializing Flask test client...")
    app.config['TESTING'] = True
    app.config['PROPAGATE_EXCEPTIONS'] = True
    
    client = app.test_client()

    print("\n1. Simulating login POST request...")
    try:
        response = client.post('/login', data={
            'username': 'Raj',
            'password': 'thisIsRaj@12345'
        }, follow_redirects=False)
        print("Login Response Status:", response.status_code)
        print("Login Redirect Location:", response.headers.get('Location'))
    except Exception as e:
        print("EXCEPTION DURING LOGIN:")
        import traceback
        traceback.print_exc()
        return

    # Simulate requesting dashboard
    print("\n2. Simulating request to dashboard...")
    try:
        response2 = client.get('/')
        print("Dashboard Response Status:", response2.status_code)
    except Exception as e:
        print("EXCEPTION DURING DASHBOARD LOAD:")
        import traceback
        traceback.print_exc()
        return

    print("\nSimulation completed successfully!")

if __name__ == '__main__':
    main()

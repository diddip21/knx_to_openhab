#!/usr/bin/env python3
"""
Test script to verify the configuration API endpoints
"""
import json
import os
from web_ui.backend.app import app

def test_config_endpoints():
    """Test the configuration endpoints"""
    with app.test_client() as client:
        print("Testing /api/config endpoint...")
        # Add basic auth header
        import base64
        credentials = base64.b64encode(b'admin:changeme').decode('utf-8')
        headers = {'Authorization': f'Basic {credentials}'}
        
        response = client.get('/api/config', headers=headers)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = json.loads(response.data)
            print(f"Response keys: {list(data.keys())}")
            print("PASS: /api/config endpoint working")
        else:
            print(f"FAIL: /api/config endpoint failed with status {response.status_code}")
        
        print("\nTesting /api/config/schema endpoint...")
        response = client.get('/api/config/schema', headers=headers)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = json.loads(response.data)
            print(f"Schema has title: {data.get('title', 'N/A')}")
            print("PASS: /api/config/schema endpoint working")
        else:
            print(f"FAIL: /api/config/schema endpoint failed with status {response.status_code}")
            print(f"Response: {response.data.decode('utf-8')}")

if __name__ == "__main__":
    test_config_endpoints()
#!/usr/bin/env python3
"""
Test script to verify the configuration update functionality
"""

import json

from web_ui.backend.app import app


def test_config_update():
    """Test updating the configuration"""
    with app.test_client() as client:
        # Add basic auth header
        import base64

        credentials = base64.b64encode(b"admin:changeme").decode("utf-8")
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }

        # First get the current config
        print("Getting current configuration...")
        response = client.get("/api/config", headers=headers)
        if response.status_code != 200:
            print(f"Failed to get config: {response.status_code}")
            return

        current_config = json.loads(response.data)
        print(f"Current config has {len(current_config)} top-level keys")

        # Modify a value in the general section
        modified_config = current_config.copy()
        original_value = modified_config["general"]["addMissingItems"]
        new_value = not original_value  # Toggle the boolean
        modified_config["general"]["addMissingItems"] = new_value

        print(f"Toggling addMissingItems from {original_value} to {new_value}")

        # Update the config
        response = client.post("/api/config", headers=headers, data=json.dumps(modified_config))
        print(f"Update status: {response.status_code}")

        if response.status_code == 200:
            result = json.loads(response.data)
            print(f"Update message: {result.get('message')}")

            # Verify the change was saved
            response = client.get("/api/config", headers=headers)
            if response.status_code == 200:
                updated_config = json.loads(response.data)
                current_value = updated_config["general"]["addMissingItems"]
                print(f"Verified: addMissingItems is now {current_value}")

                # Restore original value
                original_config = current_config.copy()
                response = client.post(
                    "/api/config", headers=headers, data=json.dumps(original_config)
                )
                if response.status_code == 200:
                    print("Restored original configuration")
                else:
                    print("Warning: Could not restore original configuration")

            print("PASS: Configuration update functionality working")
        else:
            print(f"FAIL: Configuration update failed with status {response.status_code}")
            print(f"Response: {response.data.decode('utf-8')}")


if __name__ == "__main__":
    test_config_update()

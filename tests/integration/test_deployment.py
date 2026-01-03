import os
import shutil
import pytest
import json
from pathlib import Path
from web_ui.backend.jobs import JobManager

@pytest.fixture
def mock_openhab_dir(tmp_path):
    """Create a mock openHAB directory structure."""
    oh_dir = tmp_path / "openhab"
    (oh_dir / "items").mkdir(parents=True)
    (oh_dir / "things").mkdir(parents=True)
    (oh_dir / "sitemaps").mkdir(parents=True)
    (oh_dir / "persistence").mkdir(parents=True)
    
    # Create some dummy files
    (oh_dir / "items" / "old.items").write_text("// old items")
    
    return oh_dir

@pytest.fixture
def job_manager(tmp_path, mock_openhab_dir):
    """Create a JobManager instance for testing."""
    jobs_dir = tmp_path / "jobs"
    backups_dir = tmp_path / "backups"
    jobs_dir.mkdir()
    backups_dir.mkdir()
    
    cfg = {
        'jobs_dir': str(jobs_dir),
        'backups_dir': str(backups_dir),
        'openhab_path': str(mock_openhab_dir),
        'items_path': str(mock_openhab_dir / "items" / "knx.items"),
        'things_path': str(mock_openhab_dir / "things" / "knx.things"),
        'sitemaps_path': str(mock_openhab_dir / "sitemaps" / "knx.sitemap"),
        'influx_path': str(mock_openhab_dir / "persistence" / "influxdb.persist"),
        'fenster_path': str(mock_openhab_dir / "rules" / "fenster.rules")
    }
    
    return JobManager(cfg)

def test_deploy_flow(job_manager, mock_openhab_dir, tmp_path):
    """Test the full flow from staged job to deployment."""
    # 1. Create a "completed" staged job manually for testing
    job_id = "test-job-123"
    staging_dir = tmp_path / "jobs" / job_id / "staging"
    staging_dir.mkdir(parents=True)
    
    # Create some staged files
    staged_items = staging_dir / "openhab" / "items" / "knx.items"
    staged_items.parent.mkdir(parents=True)
    staged_items.write_text("// new items")
    
    staged_things = staging_dir / "openhab" / "things" / "knx.things"
    staged_things.parent.mkdir(parents=True)
    staged_things.write_text("// new things")
    
    # Setup job state
    job = {
        'id': job_id,
        'status': 'completed',
        'staged': True,
        'staging_dir': str(staging_dir),
        'stage_mapping': {
            str(staged_items): str(mock_openhab_dir / "items" / "knx.items"),
            str(staged_things): str(mock_openhab_dir / "things" / "knx.things")
        },
        'backups': []
    }
    
    job_manager._jobs[job_id] = job
    
    # 2. Deploy
    success, msg = job_manager.deploy(job_id)
    
    assert success is True
    assert "Deployed 2 files" in msg
    
    # 3. Verify files are in target directory
    new_items_file = mock_openhab_dir / "items" / "knx.items"
    new_things_file = mock_openhab_dir / "things" / "knx.things"
    
    assert new_items_file.exists()
    assert new_items_file.read_text() == "// new items"
    
    assert new_things_file.exists()
    assert new_things_file.read_text() == "// new things"
    
    # 4. Verify backup was created
    assert len(job['backups']) == 1
    assert os.path.exists(job['backups'][0]['path'])

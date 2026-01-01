"""Configuration validator using JSON Schema"""

import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# JSON Schema for config.json
CONFIG_SCHEMA = {
    "type": "object",
    "required": ["datapoint_types", "defines", "datapoint_mappings"],
    "properties": {
        "datapoint_types": {
            "type": "object",
            "description": "Mapping of device types to their DPT",
            "properties": {
                "dimmer": {"type": "string"},
                "switch": {"type": "string"},
                "rollershutter": {"type": "string"},
                "heating": {"type": "string"},
                "heating_mode": {"type": "string"},
                "scene": {"type": "string"},
                "window_contact": {"type": "string"}
            }
        },
        "defines": {
            "type": "object",
            "description": "Device-specific configurations"
        },
        "datapoint_mappings": {
            "type": "object",
            "description": "Mappings for generic DPT types"
        },
        "general": {
            "type": "object",
            "properties": {
                "FloorNameFromDescription": {"type": "boolean"},
                "RoomNameFromDescription": {"type": "boolean"},
                "addMissingItems": {"type": "boolean"}
            }
        },
        "items_path": {"type": "string"},
        "things_path": {"type": "string"},
        "sitemaps_path": {"type": "string"},
        "influx_path": {"type": "string"},
        "fenster_path": {"type": "string"}
    }
}


class ConfigValidationError(Exception):
    """Raised when configuration validation fails"""
    pass


class ConfigValidator:
    """Validates configuration files"""
    
    def __init__(self, schema: Optional[Dict] = None):
        """Initialize validator with schema."""
        self.schema = schema or CONFIG_SCHEMA
        self.errors = []
    
    def validate(self, config: Dict) -> bool:
        """
        Validate configuration against schema.
        
        Args:
            config: Configuration dictionary to validate
            
        Returns:
            True if valid, False otherwise
            
        Raises:
            ConfigValidationError: If validation fails with details
        """
        self.errors = []
        
        # Check required fields
        for required_field in self.schema.get('required', []):
            if required_field not in config:
                self.errors.append(f"Missing required field: {required_field}")
        
        # Validate datapoint_types
        if 'datapoint_types' in config:
            self._validate_datapoint_types(config['datapoint_types'])
        
        # Validate defines
        if 'defines' in config:
            self._validate_defines(config['defines'])
        
        # Validate datapoint_mappings
        if 'datapoint_mappings' in config:
            self._validate_datapoint_mappings(config['datapoint_mappings'])
        
        # Validate paths
        if 'items_path' in config:
            self._validate_path(config['items_path'], 'items_path')
        if 'things_path' in config:
            self._validate_path(config['things_path'], 'things_path')
        
        if self.errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in self.errors)
            raise ConfigValidationError(error_msg)
        
        logger.info("Configuration validation successful")
        return True
    
    def _validate_datapoint_types(self, datapoint_types: Dict):
        """Validate datapoint_types section."""
        required_types = ['dimmer', 'switch', 'rollershutter', 'heating']
        for dt in required_types:
            if dt not in datapoint_types:
                self.errors.append(f"Missing datapoint type: {dt}")
            elif not isinstance(datapoint_types[dt], str):
                self.errors.append(f"Datapoint type '{dt}' must be a string")
    
    def _validate_defines(self, defines: Dict):
        """Validate defines section."""
        for device_type, definition in defines.items():
            if not isinstance(definition, dict):
                self.errors.append(f"Define '{device_type}' must be a dictionary")
                continue
            
            # Check for suffix configurations
            if device_type in ['dimmer', 'rollershutter', 'heating', 'switch']:
                # Each should have some suffix definitions
                has_suffix = any(key.endswith('_suffix') for key in definition.keys())
                if not has_suffix and device_type != 'drop_words':
                    self.errors.append(f"Define '{device_type}' should have at least one _suffix configuration")
    
    def _validate_datapoint_mappings(self, mappings: Dict):
        """Validate datapoint_mappings section."""
        required_fields = ['item_type', 'ga_prefix', 'item_icon', 'semantic_info']
        
        for dpt, mapping in mappings.items():
            if not isinstance(mapping, dict):
                self.errors.append(f"Mapping for '{dpt}' must be a dictionary")
                continue
            
            for field in required_fields:
                if field not in mapping:
                    self.errors.append(f"Mapping '{dpt}' missing required field: {field}")
    
    def _validate_path(self, path: str, field_name: str):
        """Validate that path is a non-empty string."""
        if not isinstance(path, str):
            self.errors.append(f"Path '{field_name}' must be a string")
        elif not path:
            self.errors.append(f"Path '{field_name}' cannot be empty")


def validate_config_file(config_path: str) -> Dict:
    """
    Load and validate configuration file.
    
    Args:
        config_path: Path to config.json
        
    Returns:
        Validated configuration dictionary
        
    Raises:
        ConfigValidationError: If validation fails
        FileNotFoundError: If config file not found
        json.JSONDecodeError: If JSON is invalid
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    validator = ConfigValidator()
    validator.validate(config)
    
    return config

"""Data models for KNX to OpenHAB conversion.

This package contains data classes and models used throughout the application:
- KNXAddress: Represents a KNX group address with metadata
- OpenHABItem: Represents an OpenHAB item configuration
- Floor: Represents a building floor with rooms
- Room: Represents a room with devices
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any


@dataclass
class KNXAddress:
    """Represents a KNX group address with metadata."""
    address: str  # e.g., "1/2/3"
    name: str
    datapoint_type: str  # e.g., "DPST-1-1", "DPST-5-1"
    function: Optional[str] = None
    usage: Optional[str] = None
    description: Optional[str] = None
    
    def __str__(self) -> str:
        return f"{self.name} ({self.address})"


@dataclass
class OpenHABItem:
    """Represents an OpenHAB item configuration."""
    name: str
    label: str
    type: str  # e.g., "Dimmer", "Switch", "Rollershutter"
    groups: List[str]
    channel: str
    tags: List[str]
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'label': self.label,
            'type': self.type,
            'groups': self.groups,
            'channel': self.channel,
            'tags': self.tags,
            'metadata': self.metadata
        }


@dataclass
class Room:
    """Represents a room in a building."""
    name: str
    devices: List[Dict[str, Any]]
    floor: Optional[str] = None
    
    def __str__(self) -> str:
        return f"Room: {self.name} ({len(self.devices)} devices)"


@dataclass
class Floor:
    """Represents a floor in a building."""
    name: str
    level: int
    rooms: List[Room]
    
    def __str__(self) -> str:
        return f"Floor {self.level}: {self.name} ({len(self.rooms)} rooms)"
    
    def total_devices(self) -> int:
        """Calculate total number of devices on this floor."""
        return sum(len(room.devices) for room in self.rooms)


__all__ = [
    'KNXAddress',
    'OpenHABItem',
    'Room',
    'Floor',
]

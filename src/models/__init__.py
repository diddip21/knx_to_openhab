"""Data models and structures"""

from dataclasses import dataclass
from typing import Optional, List, Dict

@dataclass
class KNXAddress:
    """Represents a KNX group address"""
    address: str
    group_name: str
    datapoint_type: str
    description: str = ""
    communication_objects: List[Dict] = None
    
    def __post_init__(self):
        if self.communication_objects is None:
            self.communication_objects = []

@dataclass
class OpenHABItem:
    """Represents an OpenHAB item"""
    name: str
    item_type: str
    label: str
    icon: str = ""
    groups: List[str] = None
    semantic_info: str = ""
    metadata: str = ""
    channel: str = ""
    
    def __post_init__(self):
        if self.groups is None:
            self.groups = []
    
    def to_openhab_format(self) -> str:
        """Convert to OpenHAB item definition string"""
        icon_str = f"<{self.icon}>" if self.icon and not self.icon.startswith('<') else self.icon
        groups_str = f"({','.join(self.groups)})" if self.groups else ""
        
        return f"{self.item_type}   {self.name}   \"{self.label}\"   {icon_str}   {groups_str}   {self.semantic_info}    {{ {self.channel} {self.metadata} }}"

@dataclass
class OpenHABThing:
    """Represents an OpenHAB thing"""
    thing_type: str
    name: str
    label: str
    config: str
    
    def to_openhab_format(self) -> str:
        """Convert to OpenHAB thing definition string"""
        return f"Type {self.thing_type}    :   {self.name}   \"{self.label}\"   [ {self.config} ]"

@dataclass
class Floor:
    """Represents a floor/level in the building"""
    number: int
    name: str
    description: str = ""
    name_short: str = ""
    rooms: List['Room'] = None
    
    def __post_init__(self):
        if self.rooms is None:
            self.rooms = []

@dataclass
class Room:
    """Represents a room"""
    number: int
    name: str
    description: str = ""
    name_short: str = ""
    addresses: List[KNXAddress] = None
    
    def __post_init__(self):
        if self.addresses is None:
            self.addresses = []

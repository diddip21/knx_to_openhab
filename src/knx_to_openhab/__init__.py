"""KNX to openHAB converter package.

This package provides tools to convert KNX ETS projects to openHAB configurations.

Main modules:
- config: Configuration management
- knxproject: KNX project parsing and processing
- generator: openHAB configuration generation
- cli: Command-line interface
"""

__version__ = '2.0.0'
__author__ = 'Patrick G'
__email__ = '38922528+diddip21@users.noreply.github.com'

from . import config
from . import knxproject
from . import generator

__all__ = ['config', 'knxproject', 'generator', '__version__']

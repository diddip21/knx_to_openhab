#!/usr/bin/env python3
"""Setup script for knx_to_openhab package."""

from setuptools import setup, find_packages
import os

# Read version from package
version_file = os.path.join(os.path.dirname(__file__), 'src', 'knx_to_openhab', '__init__.py')
version = '2.0.0'  # Default version
if os.path.exists(version_file):
    with open(version_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('__version__'):
                version = line.split('=')[1].strip().strip('"\' ')
                break

with open('README.md', 'r', encoding='utf-8') as f:
    long_description = f.read()

with open('requirements.txt', 'r', encoding='utf-8') as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name='knx_to_openhab',
    version=version,
    description='KNX ETS projects to openHAB configuration converter',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Patrick G',
    author_email='38922528+diddip21@users.noreply.github.com',
    url='https://github.com/diddip21/knx_to_openhab',
    license='MIT',
    
    # Package discovery - point to src directory
    package_dir={'': 'src'},
    packages=find_packages('src'),
    
    # Include package data
    include_package_data=True,
    package_data={
        'knx_to_openhab': [
            'config.json',
        ],
    },
    
    # Data files to include
    data_files=[
        ('', ['config.json']),  # Keep config.json in root for backward compatibility
    ],
    
    # Console entry points
    entry_points={
        'console_scripts': [
            'knx-to-openhab=knx_to_openhab.cli:main',
        ],
    },
    
    # Dependencies
    install_requires=requirements,
    
    # Python version requirement
    python_requires='>=3.8',
    
    # Classifiers
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Topic :: Home Automation',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
    ],
    
    keywords='knx ets openhab home automation',
    project_urls={
        'Bug Reports': 'https://github.com/diddip21/knx_to_openhab/issues',
        'Source': 'https://github.com/diddip21/knx_to_openhab',
        'Documentation': 'https://github.com/diddip21/knx_to_openhab/blob/main/README.md',
    },
)

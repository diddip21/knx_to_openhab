"""Command-line entry point for KNX to OpenHAB converter.

This module allows running the package as a module:
  python -m knx_to_openhab --help
  python -m knx_to_openhab <file.knxproj>
  python -m knx_to_openhab web
"""

import sys
import argparse
from pathlib import Path


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='knx-to-openhab',
        description='Convert KNX project files to OpenHAB configuration',
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='%(prog)s 1.0.0'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Main conversion command
    convert_parser = subparsers.add_parser(
        'convert',
        help='Convert KNX project file to OpenHAB configuration',
        aliases=['c']  # Allow short form
    )
    convert_parser.add_argument(
        'file_path',
        type=Path,
        help='Path to KNX project file (.knxproj or .json dump)'
    )
    convert_parser.add_argument(
        '--password', '-p',
        type=str,
        default=None,
        help='Password for encrypted KNX project file'
    )
    
    # Web UI command
    web_parser = subparsers.add_parser(
        'web',
        help='Start the web UI'
    )
    web_parser.add_argument(
        '--host',
        type=str,
        default='0.0.0.0',
        help='Bind address (default: 0.0.0.0)'
    )
    web_parser.add_argument(
        '--port',
        type=int,
        default=8085,
        help='Bind port (default: 8085)'
    )
    
    # Version command
    subparsers.add_parser('version', help='Show version information')
    
    args = parser.parse_args()
    
    # Default to 'convert' if no subcommand specified
    if args.command is None:
        # If first arg is a file path, treat as convert command
        if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
            # Reconstruct with 'convert' subcommand
            sys.argv.insert(1, 'convert')
            return main()
        parser.print_help()
        sys.exit(1)
    
    if args.command == 'version':
        print('knx-to-openhab version 1.0.0')
        sys.exit(0)
    
    if args.command in ('convert', 'c'):
        # Import here to avoid loading dependencies unless needed
        from . import knxproject
        
        # Mock sys.argv so knxproject.main() can parse it correctly
        # knxproject.main() expects to parse sys.argv itself
        original_argv = sys.argv
        try:
            # Build argv for knxproject.main()
            sys.argv = ['knx_to_openhab', '--file_path', str(args.file_path)]
            if args.password:
                sys.argv.extend(['--knxPW', args.password])
            
            # Call the main function
            knxproject.main()
        except KeyboardInterrupt:
            print('\nConversion cancelled by user.', file=sys.stderr)
            sys.exit(130)  # Standard exit code for SIGINT
        except Exception as e:
            print(f'Error: {e}', file=sys.stderr)
            sys.exit(1)
        finally:
            # Restore original sys.argv
            sys.argv = original_argv
    
    elif args.command == 'web':
        # Import here to avoid loading Flask unless needed
        try:
            from .web_ui.backend import app as web_app
            print(f'Starting web UI on http://{args.host}:{args.port}')
            web_app.app.run(host=args.host, port=args.port, debug=False)
        except ImportError as e:
            print(f'Error: Web UI dependencies not installed: {e}', file=sys.stderr)
            print('Install with: pip install -e ".[web]"', file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f'Error starting web UI: {e}', file=sys.stderr)
            sys.exit(1)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()

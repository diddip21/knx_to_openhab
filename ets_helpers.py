"""Helper functions for KNX address and flag processing.

This module contains functions extracted from gen_building() to allow
proper unit testing and code reusability. These functions handle:

- Communication object flag extraction and matching
- Data point type (DPT) extraction from device communication objects
- Address filtering based on flags and DPT types

These utilities are critical for correctly mapping KNX datapoints to
OpenHAB items in the code generator.
"""

from typing import Any, Dict, Optional


def get_co_flags(co: Dict[str, Any]) -> Optional[Dict[str, bool]]:
    """Extract communication object flags.

    Communication objects in KNX projects contain flag information that
    determines their behavior (read, write, transmit, update). This function
    safely extracts these flags from a communication object.

    Args:
        co: Communication object dictionary with optional 'flags' key.
               Expected structure: {'flags': {'read': bool, 'write': bool, ...}}

    Returns:
        Dictionary with flag values (read, write, transmit, update) with
        defaults of False for missing flags. Returns None if the CO has
        no flags attribute.

    Example:
        >>> co = {'text': 'Status', 'flags': {'read': True, 'write': False}}
        >>> flags = get_co_flags(co)
        >>> flags['read']
        True
        >>> flags['write']
        False
        >>> flags.get('transmit', False)
        False
    """
    if not isinstance(co, dict) or "flags" not in co:
        return None

    flags_data = co.get("flags", {})
    if not isinstance(flags_data, dict):
        return None

    return {
        "read": flags_data.get("read", False),
        "write": flags_data.get("write", False),
        "transmit": flags_data.get("transmit", False),
        "update": flags_data.get("update", False),
    }


def flags_match(
    co_flags: Optional[Dict[str, bool]], expected_flags: Optional[Dict[str, bool]]
) -> bool:
    """Check if communication object flags match expected flags.

    This function compares actual communication object flags with a set of
    expected flags. It's used to filter communication objects based on their
    capabilities (e.g., finding only writable objects for commands, or only
    readable objects for status feedback).

    Filtering logic:
    - If either co_flags or expected_flags is None/empty, returns True
      (no filtering requested)
    - Otherwise, ALL expected flags must match the CO flags
    - Extra flags in CO (not in expected set) are ignored
    - Missing flags in CO are treated as False

    Args:
        co_flags: Actual CO flags (from get_co_flags). Can be None for
                 no filtering.
        expected_flags: Flags we're looking for. Can be None or empty
                       dict for no filtering. Example: {'read': True, 'write': False}

    Returns:
        True if all expected flags match (or no filtering is requested),
        False if any expected flag doesn't match.

    Example - Command filtering (write=True):
        >>> co_flags = {'read': False, 'write': True, 'transmit': False, 'update': False}
        >>> expected = {'write': True}
        >>> flags_match(co_flags, expected)
        True

    Example - Status filtering (read=True, transmit=True):
        >>> co_flags = {'read': True, 'write': False, 'transmit': True, 'update': False}
        >>> expected = {'read': True, 'transmit': True}
        >>> flags_match(co_flags, expected)
        True

    Example - Mismatch:
        >>> co_flags = {'read': False, 'write': False, 'transmit': True, 'update': False}
        >>> expected = {'read': True}
        >>> flags_match(co_flags, expected)
        False
    """
    # None or empty dict means no filtering required
    if not co_flags or not expected_flags:
        return True

    # Check each expected flag
    for flag_name, flag_value in expected_flags.items():
        # If the flag doesn't match, exclude this CO
        if co_flags.get(flag_name, False) != flag_value:
            return False

    return True


def get_dpt_from_dco(dco: Dict[str, Any]) -> Optional[str]:
    """Extract and format DPT from a device communication object.

    Data Point Types (DPT) define the semantics and physical representation
    of data in KNX. Each device communication object can have associated DPTs.
    This function extracts the first DPT and formats it as a string.

    Args:
        dco: Device communication object dictionary with potential 'dpts' key.
             Expected structure: {'dpts': [{'main': int, 'sub': int}, ...]}

    Returns:
        Formatted DPT string in format "main.sub" (e.g., "1.001" for DPT 1.001)
        with sub-type zero-padded to 3 digits. Returns None if:
        - dco is not a dict
        - dco has no dpts array
        - dpts array is empty or invalid
        - DPT doesn't have both 'main' and 'sub' fields

    Example:
        >>> dco = {'dpts': [{'main': 5, 'sub': 1}]}
        >>> get_dpt_from_dco(dco)
        '5.001'

    Example - Missing sub:
        >>> dco = {'dpts': [{'main': 1}]}
        >>> get_dpt_from_dco(dco) is None
        True

    Example - No DPTs:
        >>> dco = {'text': 'Some Object'}
        >>> get_dpt_from_dco(dco) is None
        True
    """
    if not isinstance(dco, dict):
        return None

    dpts = dco.get("dpts", [])

    # Validate dpts is a list and not empty
    if not dpts or not isinstance(dpts, list) or len(dpts) == 0:
        return None

    # Get first DPT
    first_dpt = dpts[0]
    if not isinstance(first_dpt, dict):
        return None

    # Extract main and sub values
    main = first_dpt.get("main")
    sub = first_dpt.get("sub")

    # Both main and sub must be present
    if main is None or sub is None:
        return None

    # Format as "main.sub" with sub zero-padded to 3 digits
    return f"{main}.{sub:03d}"

from typing import Dict, Optional

def read_config_file(path: str, key_to_uppercase=False) -> Dict[str, Optional[str]]:
    """
    Reads a config file and returns a dictionary of key-value pairs.
    """
    result = dict[str, Optional[str]]()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                if key_to_uppercase:
                    key = key.upper()
                if value:
                    result[key.strip()] = value.strip()
                else:
                    result[key.strip()] = None
    return result

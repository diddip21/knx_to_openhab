import json
import re
import logging
logger = logging.getLogger(__name__)

config=[]
def normalize_string(text: str):
    """Remove non-alphanumeric characters and convert to lowercase (unicode)."""
    return re.sub(r'\W+','', text.casefold())

def main():
    """Main function"""
    with open('config.json', encoding='utf8') as f:
        cfg = json.load(f)
    def _normalize(v):
        if isinstance(v, dict):
            v=_normalize_dict(v)
        elif isinstance(v, list):
            v=_normalize_list(v)
        elif isinstance(v, tuple):
            v=_normalize_list(v)
        elif isinstance(v,str):
            v = normalize_string(v)
        return v
    def _normalize_list(l):
        """Recursively normalizes strings within a list in-place."""
        for idx, v in enumerate(l):
            l[idx]=_normalize(v)
        return l
    def _normalize_dict(d):
        """Recursively normalizes strings within a dictionary in-place."""
        for v in d.items():
            v=_normalize(v)
        return d
    for idef in cfg['defines']:
        if isinstance(cfg['defines'][idef],dict):
            for xidef in cfg['defines'][idef]:
                if 'suffix' in xidef:
                    if isinstance(cfg['defines'][idef][xidef],list):
                        cfg['defines'][idef][xidef] = [normalize_string(element) for element in cfg['defines'][idef][xidef]]
                        #remove duplicates
                        cfg['defines'][idef][xidef] = list(set(cfg['defines'][idef][xidef]))
    global config
    config = cfg

#if __name__ == "__main__":
main()
config['special_char_map'] = {
    ord('Ä'):'Ae',
    ord('Ü'):'Ue',
    ord('Ö'):'Oe',
    ord('ä'):'ae',
    ord('ü'):'ue',
    ord('ö'):'oe',
    ord('ß'):'ss',
    ord('é'):'e',
    ord('è'):'e',
    ord('á'):'a',
    ord('à'):'a'
}

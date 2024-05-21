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
# Mappings für Datenpunkttypen
datapoint_mappings = {
    # Tag / Nacht
    'DPST-1-24': {'item_type': 'Switch', 'ga_prefix': '1.024', 'metadata': '','semantic_info':"[\"Control\"]", 'item_icon':"moon"},
    # Alarm
    'DPST-1-5': {'item_type': 'Switch', 'ga_prefix': '1.005', 'metadata': '','semantic_info':"[\"Alarm\"]", 'item_icon':"siren"},
    # Status
    'DPST-1-11': {'item_type': 'Switch', 'ga_prefix': '1.011', 'metadata': '','semantic_info':"[\"Measurement\", \"Status\"]", 'item_icon':"switch"},
    # Heizen / Kühlen
    'DPST-1-100': {'item_type': 'Switch', 'ga_prefix': '1.100', 'metadata': '','semantic_info':"[\"Measurement\", \"Status\"]", 'item_icon':"temperature"},
    # Temperatur
    'DPST-9-1': {'item_type': 'Number:Temperature', 'ga_prefix': '9.001', 'metadata': ', stateDescription=\"\"[pattern=\"%.1f %unit%\"]',
                    'semantic_info':"[\"Measurement\", \"Temperature\"]", 'item_icon':"temperature"},
    # Luftfeuchtigkeit
    'DPST-9-7': {'item_type': 'Number:Dimensionless', 'ga_prefix': '9.001', 'metadata': ', unit=\"%\", stateDescription=\"\"[pattern=\"%.1f %%\"]',
                    'semantic_info':"[\"Measurement\", \"Humidity\"]", 'item_icon':"humidity"},
    # Fensterkontakt
    'DPST-1-19': {'item_type': 'Contact', 'ga_prefix': '1.019', 'metadata': ', unit=\"%\", stateDescription=\"\"[pattern=\"%.1f %%\"]',
                    'semantic_info':"[\"OpenState\", \"Opening\"]", 'item_icon':"window"},
    # Energie
    'DPST-13-10': {'item_type': 'Number:Energy', 'ga_prefix': '13.010', 'metadata': ', stateDescription=\"\"[pattern=\"%.1f %unit%\"]',
                    'semantic_info':"[\"Measurement\", \"Energy\"]", 'item_icon':"batterylevel"},
    # Leistung
    'DPST-14-56': {'item_type': 'Number:Power', 'ga_prefix': '14.056', 'metadata': ', stateDescription=\"\"[pattern=\"%.1f %unit%\"]',
                    'semantic_info':"[\"Measurement\", \"Power\"]", 'item_icon':"energy"},
    # Strom
    'DPST-7-12': {'item_type': 'Number:ElectricCurrent', 'ga_prefix': '7.012', 'metadata': ', stateDescription=\"\"[pattern=\"%.1f %unit%\"]',
                    'semantic_info':"[\"Measurement\", \"Current\"]", 'item_icon':"energy"},
    # Volumen (l)
    'DPST-12-1200': {'item_type': 'Number:Volume', 'ga_prefix': '12.1200', 'metadata': ', stateDescription=\"\"[pattern=\"%.1f %unit%\"]',
                    'semantic_info':"[\"Measurement\", \"Volume\"]", 'item_icon':"water"},
    # String
    'DPST-16-0': {'item_type': 'String', 'ga_prefix': '16.000', 'metadata': '','semantic_info':"", 'item_icon':"text"},
    'DPT-16': {'item_type': 'String', 'ga_prefix': '16.000', 'metadata': '','semantic_info':"", 'item_icon':"text"},
    # Beleuchtungsstärke (Lux)
    'DPST-9-4': {'item_type': 'Number:Illuminance', 'ga_prefix': '9.004', 'metadata': ', stateDescription=\"\"[pattern=\"%.1f %unit%\"]',
                    'semantic_info':"[\"Measurement\", \"Light\"]", 'item_icon':"sun"},
    # Geschwindigkeit (m/s)
    'DPST-9-5': {'item_type': 'Number:Speed', 'ga_prefix': '9.005', 'metadata': ', unit="m/s", stateDescription=\"\"[pattern=\"%.1f %unit%\"]',
                    'semantic_info':"[\"Measurement\", \"Wind\"]", 'item_icon':"wind"},
    # Luftqualität (ppm)
    'DPST-9-8': {'item_type': 'Number:Dimensionless', 'ga_prefix': '9.005', 'metadata': ', stateDescription=\"\"[pattern=\"%.1f ppm\"]',
                    'semantic_info':"[\"Measurement\"]", 'item_icon':""},
    # Prozent
    'DPST-5-1': {'item_type': 'Dimmer', 'ga_prefix': 'position=5.001', 'metadata': ', unit=\"%\", stateDescription=\"\"[pattern=\"%.1f %%\"]',
                    'semantic_info':"[\"Measurement\"]", 'item_icon':""},
    # Zeitdifferenz
    'DPST-13-100': {'item_type': 'Number:Time', 'ga_prefix': '13.100', 'metadata': ', stateDescription=\"\"[pattern=\"%.1f %unit%\"]',
                    'semantic_info':"[\"Measurement\", \"Duration\"]", 'item_icon':"time"},
    # Datum/Uhrzeit
    'DPST-19-1': {'item_type': 'DateTime', 'ga_prefix': '19.001', 'metadata': '', 'semantic_info':"", 'item_icon':"time"},
    # Betriebsartvorwahl
    'DPST-20-102': {'item_type': 'Number:Dimensionless', 'ga_prefix': '20.102', 'metadata': ', stateDescription=\"\"[options=\"NULL=unbekannt ...,1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"], commandDescription=\"\"[options=\"1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"], listWidget=\"\"[iconUseState=\"true\"]',
                    'semantic_info':"[\"HVAC\"]", 'item_icon':"heating_mode"},
    'DPST-5-010': {'item_type': 'Number:Dimensionless', 'ga_prefix': '5.010', 'metadata': ', stateDescription=\"\"[options=\"NULL=unbekannt ...,1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"], commandDescription=\"\"[options=\"1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"], listWidget=\"\"[iconUseState=\"true\"]',
                    'semantic_info':"[\"HVAC\"]", 'item_icon':"heating_mode"},
}

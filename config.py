import json
with open('config.json', encoding='utf8') as f:
    config = json.load(f)

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

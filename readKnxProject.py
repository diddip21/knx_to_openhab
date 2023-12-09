#pip install xknxproject

"""Extract and parse a KNX project file."""
from xknxproject.models import KNXProject
from xknxproject import XKNXProj

import re, json
import configparser
config = configparser.ConfigParser()

default_pattern_item_Room = r"\++[A-Z].[0-9]+"
default_pattern_item_Floor = r"=[A-Z]+"
default_pattern_item_Floor_nameshort = r'[A-Z]. ' #^[a-zA-Z]{1,5}$
default_item_Floor_nameshort_prefix = r"="

config['knxproject']= {}
cknxproject = config['knxproject']
cknxproject['path']=r'.\myknxproject.knxproj'

config['RegexPattern']= {}
cregpatt = config['RegexPattern']
cregpatt['item_Floor']=default_pattern_item_Floor
cregpatt['item_Floor_nameshort']=default_pattern_item_Floor_nameshort
cregpatt['item_Room']=default_pattern_item_Room

config['defaults']= {}
cdefaults = config['defaults']
cdefaults['item_Floor_nameshort_prefix']=default_item_Floor_nameshort_prefix

with open('example.ini', 'w') as configfile:
  config.write(configfile)

config.read('config.ini')

pattern_item_Room=config['RegexPattern'].get('item_Room',default_pattern_item_Room)
pattern_item_Floor=config['RegexPattern'].get('item_Floor',default_pattern_item_Floor)
pattern_floor_nameshort=config['RegexPattern'].get('item_Floor_nameshort',default_pattern_item_Floor_nameshort)
item_Floor_nameshort_prefix=config['defaults'].get('item_Floor_nameshort_prefix',default_item_Floor_nameshort_prefix)

#cregpatt.get('CompressionLevel', '3')

knxproj: XKNXProj = XKNXProj(
    path=r"C:\Users\Username\Nextcloud\LogiHome\xx_ETS\Archiv\Charne.knxprojarchive",
    #path="Dr.knxproj",
    #path=r"C:\Users\Username\Nextcloud\LogiHome\xx_ETS\Archiv\Brückner.knxprojarchive",
    #path=r"C:\Users\Username\Nextcloud\LogiHome\xx_ETS\Archiv\Selzam.knxprojarchive",
    #path=r"C:\Users\Username\Nextcloud\LogiHome\xx_ETS\Archiv\Dr. Keß, Praxis.knxprojarchive",
    #password="password",  # optional
    language="de-DE",  # optional
)
project: KNXProject = knxproj.parse()

re_item_Room =re.compile(pattern_item_Room)
re_item_Floor =re.compile(pattern_item_Floor)
re_floor_nameshort =re.compile(pattern_floor_nameshort)

def createBuilding(locations):
    if len(locations)==0:
        raise ValueError("'locations' is Empty.")
    prj = []
    for loc in locations.values():
        if loc['type'] in ('Building','BuildingPart'):
            prj.append({
                'description':loc['description'],
                'name_long':loc['name'],
                'name_short':None,
                'floors':[]
                })
            prj_loc=prj[-1]
        for floor in loc['spaces'].values():
            if floor['type'] in ('Floor','Stairway','Corridor','BuildingPart'):
                prj_loc['floors'].append({
                    'description':floor['description'],
                    'name_long':floor['description'],
                    'name_short':None,
                    'rooms':[]
                    })
                prj_floor=prj_loc['floors'][-1]
                res = re_floor_nameshort.search(floor['name'])
                if res is not None:
                    if res.group(0).startswith(item_Floor_nameshort_prefix):
                        prj_floor['name_short']=res.group(0)
                    else:
                        prj_floor['name_short']=item_Floor_nameshort_prefix+res.group(0)
                elif not floor['name'].startswith(item_Floor_nameshort_prefix) and len(floor['name']) < 6:
                    prj_floor['name_short']=item_Floor_nameshort_prefix+floor['name']
                else:
                    prj_floor['description']=floor['name']
                    prj_floor['name_short']=item_Floor_nameshort_prefix+floor['name']
                if prj_floor['description'] == '':
                    prj_floor['description']=floor['name']
                for room in floor['spaces'].values():
                    if room['type'] == 'Room':
                        prj_floor['rooms'].append({
                            'description':room['description'],
                            'name_long':room['description'],
                            'name_short':None,
                        })
                        prj_room=prj_floor['rooms'][-1]
                        resFloor = re_item_Floor.search(room['name'])
                        resRoom = re_item_Room.search(room['name'])
                        roomNamePlain = room['name']
                        roomNameLong = ''
                        if resFloor is not None:
                            roomNameLong+=resFloor.group(0)
                            roomNamePlain=str.replace(roomNamePlain,resFloor.group(0),"").strip()
                            if prj_floor['name_short']==floor['name'] or prj_floor['name_short']==item_Floor_nameshort_prefix+floor['name']:
                                prj_floor['name_short']=resFloor.group(0)
                                prj_floor['description']=str.replace(floor['name'],resFloor.group(0),"").strip()
                        else:
                            if not prj_floor['name_short'] == '':
                                roomNameLong+=prj_floor['name_short']
                            else:
                                roomNameLong+='=XX'
                        if resRoom is not None:
                            roomNameLong+=resRoom.group(0)
                            roomNamePlain=str.replace(roomNamePlain,resRoom.group(0),"").strip()
                            prj_room['name_short']=resRoom.group(0)
                        else:
                            prj_room['name_short']='+RMxx'
                            roomNameLong+='+RMxx'
                        if roomNamePlain == '':
                            roomNamePlain=room['usage_text']
                        prj_room['description']=roomNamePlain
                        if prj_room['name_long'] == '':
                            prj_room['name_long']=roomNameLong
                        #print(f"Room: {room['name']} -> {room['name_short']} - {room['name_long']}")
                if prj_floor['name_long'] == '':
                    prj_floor['name_long']=prj_floor['name_short']
                #print(f"Floor: {floor['name']} -> {floor['name_short']} - {floor['name_long']}")
    return prj

def getAddresses(groupaddresses):
    if len(groupaddresses)==0:
        raise ValueError("'groupaddresses' is Empty.")
    _addresses = []
    for address in groupaddresses.values():
        ignore = False
        if 'ignore' in address['comment'] or not address['communication_object_ids']:
            print(f"Ignore: {address['name']}")
            ignore = True
        else:
            resRoom = re_item_Room.search(address['name'])
            resFloor = re_item_Floor.search(address['name'])
            if resRoom:
                print(f"OK: {address['name']} - {resRoom.group(0)}")
            else:
                print(f"OK: {address['name']} - No Room detected: {address['name']}")
            if resFloor:
                print(f"     {address['name']} -> {resFloor.group(0)}")    
           
        if not ignore:
            _addresses.append({})
            laddress=_addresses[-1]
            laddress["Group name"]=address["name"]
            laddress["Address"]=address["address"]
            laddress["Description"]=address["description"]
            laddress["DatapointType"] = "DPST-{}-{}".format(address["dpt"]["main"],address["dpt"]["sub"])  if address["dpt"]["sub"] else "DPT-{}".format(address["dpt"]["main"]) 
    return _addresses            
            



building=createBuilding(project['locations'])
pretty = json.dumps(building, indent=2, ensure_ascii=False)#, sort_keys=True)
print(pretty)


addresses=getAddresses(project['group_addresses'])
#print(addresses)
readDump=True
#pip install xknxproject
#pip install git+https://github.com/XKNX/xknxproject.git

"""Extract and parse a KNX project file."""
from xknxproject.models import KNXProject
from xknxproject import XKNXProj

#from ets_to_openhab import house,genBuilding,check_unusedAddresses,export_output
import ets_to_openhab

import re, json
import configparser
config = configparser.ConfigParser()

addUnkownItemsToEnd=True
default_Floor="unkonwn"
default_Room="unknown"
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

if readDump:
    proj: KNXProject
    with open("tests/Dr. Keß, Praxis.knxprojarchive.json", encoding="utf-8") as f:
        project = json.load(f)
else:
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

def createBuilding(project: KNXProject):
    locations = project['locations']
    if len(locations)==0:
        raise ValueError("'locations' is Empty.")
    prj = []
    for loc in locations.values():
        if loc['type'] in ('Building','BuildingPart'):
            prj.append({
                'Description':loc['description'],
                'Group name':loc['name'],
                'name_long':loc['name'],
                'name_short':None,
                'floors':[]
                })
            prj_loc=prj[-1]
        for floor in loc['spaces'].values():
            if floor['type'] in ('Floor','Stairway','Corridor','BuildingPart'):
                prj_loc['floors'].append({
                    'Description':floor['description'],
                    'Group name':None,
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
                    prj_floor['Description']=floor['name']
                    prj_floor['name_short']=item_Floor_nameshort_prefix+floor['name']
                if prj_floor['Description'] == '':
                    prj_floor['Description']=floor['name']
                for room in floor['spaces'].values():
                    if room['type'] == 'Room':
                        prj_floor['rooms'].append({
                            'Description':room['description'],
                            'Group name':None,
                            'name_long':room['description'],
                            'name_short':None,
                            'Addresses':[]
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
                                prj_floor['Description']=str.replace(floor['name'],resFloor.group(0),"").strip()
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
                        prj_room['Description']=roomNamePlain
                        if prj_room['name_long'] == '':
                            prj_room['name_long']=roomNameLong
                        if not prj_room['Group name']:
                            prj_room['Group name']=prj_room['name_short']
                        #print(f"Room: {room['name']} -> {room['name_short']} - {room['name_long']}")
                if prj_floor['name_long'] == '':
                    prj_floor['name_long']=prj_floor['name_short']
                if not prj_floor['Group name']:
                    prj_floor['Group name']=prj_floor['name_short']
                #print(f"Floor: {floor['name']} -> {floor['name_short']} - {floor['name_long']}")
    return prj

def getAddresses(project: KNXProject):
    groupaddresses=project['group_addresses']
    if len(groupaddresses)==0:
        raise ValueError("'groupaddresses' is Empty.")
    communication_objects=project["communication_objects" ]
    if len(communication_objects)==0:
        raise ValueError("'communication_objects' is Empty.")
    devices=project["devices"]
    if len(devices)==0:
        raise ValueError("'devices' is Empty.")
    group_ranges=project["group_ranges"]
    if len(group_ranges)==0:
        raise ValueError("'group_ranges' is Empty.")  
    _addresses = []
    for address in groupaddresses.values():
        ignore = False
        if 'ignore' in address['comment']:
            print(f"Ignore: {address['name']}")
            ignore = True
        elif not address['communication_object_ids']:
            print(f"Ignore: {address['name']} because no communication object connected")
            ignore = True
        else:
            resRoom = re_item_Room.search(address['name'])
            resFloor = re_item_Floor.search(address['name'])
            if not resFloor:
                address_split = address['address'].split("/")
                grTop =group_ranges.get(address_split[0])
                grMiddle =grTop['group_ranges'].get(address_split[0] + "/" + address_split[1])
                resFloor = re_item_Floor.search(grMiddle['name'])
                if not resFloor:
                    resFloor = re_item_Floor.search(grTop['name'])
                    if not resFloor:
                        resFloor = re_floor_nameshort.search(grMiddle['name'])
                        if not resFloor:
                            resFloor = re_floor_nameshort.search(grTop['name'])
            # if resRoom:
            #     print(f"OK: {address['name']} - {resRoom.group(0)}")
            # else:
            #     print(f"OK: {address['name']} - No Room detected: {address['name']}")
            # if resFloor:
            #     print(f"     {address['name']} -> {resFloor.group(0)}")    
           
        if not ignore:
            _addresses.append({})
            laddress=_addresses[-1]
            laddress["Group name"]=address["name"]
            laddress["Address"]=address["address"]
            laddress["Description"]=address["description"]
            laddress["communication_object"]=[]
            for co_id in address['communication_object_ids']:
                co_o = communication_objects[co_id]
                if co_o['flags']:
                    if co_o['flags']['read'] or co_o['flags']['write']:
                        device_id = co_o['device_address']
                        device_o=devices[device_id]
                        if device_o['communication_object_ids']:
                            co_o["device_communication_objects"]=[]
                            for device_co_id in device_o['communication_object_ids']:
                                device_co_o = communication_objects[device_co_id]
                                if co_o['channel']:
                                    if co_o['channel'] == device_co_o["channel"]:# and co_o["number"] != device_co_o["number"]:
                                        co_o["device_communication_objects"].append(device_co_o)
                                else:
                                    co_o["device_communication_objects"].append(device_co_o)
                laddress["communication_object"].append(co_o)
            if resFloor:
                laddress["Floor"]=resFloor.group(0)
                if not laddress["Floor"].startswith(item_Floor_nameshort_prefix) and len(laddress["Floor"]) < 6:
                    laddress["Floor"]=item_Floor_nameshort_prefix+laddress["Floor"]
            else:
                laddress["Floor"]=default_Floor
            if resRoom:
                laddress["Room"]=resRoom.group(0)
            else:
                laddress["Room"]=default_Room
            laddress["DatapointType"] = "DPST-{}-{}".format(address["dpt"]["main"],address["dpt"]["sub"])  if address["dpt"]["sub"] else "DPT-{}".format(address["dpt"]["main"]) 
    return _addresses            

def putAddressesInBuilding(building,addresses):
    if len(building)==0:
        raise ValueError("'building' is Empty.")
    if len(addresses)==0:
        raise ValueError("'addresses' is Empty.")
    unknown =[]
    for address in addresses:
        #print (address)
        found=False
        for itembuilding in building:
            for floor in itembuilding["floors"]:
                if floor["name_short"] == address["Floor"]:
                    for room in floor["rooms"]:
                        if room["name_short"] == address["Room"]:
                            if not "Addresses" in room:
                                room["Addresses"]=[]
                            room["Addresses"].append(address)
                            found=True
                            break
        if not found:
            unknown.append(address)
            #print("add to unknown")
    if addUnkownItemsToEnd:
        building[0]["floors"].append({
                    'Description':default_Floor,
                    'Group name':default_Floor,
                    'name_long':default_Floor,
                    'name_short':default_Floor,
                    'rooms':[]
                    })
        building[0]["floors"][-1]["rooms"].append({
                            'Description':default_Room,
                            'Group name':default_Room,
                            'name_long':default_Room,
                            'name_short':default_Room,
                            'Addresses':[]
                        })
        building[0]["floors"][-1]["rooms"][-1]["Addresses"]=unknown
    else:
        print(unknown)
        print(f"Unknown addresses = '{len(unknown)}'")

    return building

building=createBuilding(project)
#pretty = json.dumps(building, indent=2, ensure_ascii=False)#, sort_keys=True)
#print(pretty)

addresses=getAddresses(project)
#print(addresses)

house=putAddressesInBuilding(building,addresses)
ets_to_openhab.house = house[0]["floors"]
ets_to_openhab.all_addresses = addresses
ets_to_openhab.genBuilding()
ets_to_openhab.check_unusedAddresses()
ets_to_openhab.export_output()

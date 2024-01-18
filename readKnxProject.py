#pip install xknxproject
#pip install git+https://github.com/XKNX/xknxproject.git

"""Extract and parse a KNX project file."""
from xknxproject.models import KNXProject
from xknxproject import XKNXProj

import ets_to_openhab

import logging
logger = logging.getLogger(__name__)
import re, json
from config import config
from pathlib import Path
import argparse
import tkinter as tk
from tkinter import filedialog

pattern_item_Room=config['regexpattern']['item_Room']
pattern_item_Floor=config['regexpattern']['item_Floor']
pattern_floor_nameshort=config['regexpattern']['item_Floor_nameshort']
item_Floor_nameshort_prefix=config['general']['item_Floor_nameshort_prefix']
item_Room_nameshort_prefix=config['general']['item_Room_nameshort_prefix']
unkown_floorname=config['general']['unkown_floorname']
unkown_roomname=config['general']['unkown_roomname']
addMissingItems=config['general']['addMissingItems']

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
                            'devices':room['devices'],
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
                                roomNameLong+=item_Floor_nameshort_prefix+'XX'
                        if resRoom is not None:
                            roomNameLong+=resRoom.group(0)
                            roomNamePlain=str.replace(roomNamePlain,resRoom.group(0),"").strip()
                            prj_room['name_short']=resRoom.group(0)
                        else:
                            prj_room['name_short']=item_Room_nameshort_prefix+'RMxx'
                            roomNameLong+=item_Room_nameshort_prefix+'RMxx'
                        if roomNamePlain == '':
                            roomNamePlain=room['usage_text']
                        prj_room['Description']=roomNamePlain
                        if prj_room['name_long'] == '':
                            prj_room['name_long']=roomNameLong
                        if not prj_room['Group name']:
                            prj_room['Group name']=prj_room['name_short']
                if prj_floor['name_long'] == '':
                    prj_floor['name_long']=prj_floor['name_short']
                if not prj_floor['Group name']:
                    prj_floor['Group name']=prj_floor['name_short']
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
            logger.info(f"Ignore: {address['name']}")
            ignore = True
        elif not address['communication_object_ids']:
            logger.info(f"Ignore: {address['name']} because no communication object connected")
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
                laddress["Floor"]=unkown_floorname
            if resRoom:
                laddress["Room"]=resRoom.group(0)
            else:
                laddress["Room"]=unkown_roomname
            laddress["DatapointType"] = "DPST-{}-{}".format(address["dpt"]["main"],address["dpt"]["sub"])  if address["dpt"]["sub"] else "DPT-{}".format(address["dpt"]["main"]) 
    return _addresses            
def _getSensorCoFromList(cos):
    if "communication_object" in cos:
        for co in cos["communication_object"]:
            if "flags" in co:
                if "read" in co["flags"]:
                    if co["flags"]["read"] == True:
                        return co
                if "transmit" in co["flags"]:
                    if co["flags"]["transmit"] == True:
                        return co
    return None
def putAddressesInBuilding(building,addresses):
    if len(building)==0:
        raise ValueError("'building' is Empty.")
    if len(addresses)==0:
        raise ValueError("'addresses' is Empty.")
    unknown =[]
    for address in addresses:
        found=False
        read_co = _getSensorCoFromList(address)
        #read_co=None
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
            if read_co:
                for floor in itembuilding["floors"]:
                    for room in floor["rooms"]:
                        if 'devices' in room:
                            if read_co['device_address'] in room['devices']:
                                 room["Addresses"].append(address)
                                 found=True
                                 break
        if not found:
            unknown.append(address)
    if addMissingItems:
        building[0]["floors"].append({
                    'Description':unkown_floorname,
                    'Group name':unkown_floorname,
                    'name_long':unkown_floorname,
                    'name_short':unkown_floorname,
                    'rooms':[]
                    })
        building[0]["floors"][-1]["rooms"].append({
                            'Description':unkown_roomname,
                            'Group name':unkown_roomname,
                            'name_long':unkown_roomname,
                            'name_short':unkown_roomname,
                            'Addresses':[]
                        })
        building[0]["floors"][-1]["rooms"][-1]["Addresses"]=unknown
    else:
        logger.info(unknown)
        logger.info(f"Unknown addresses = '{len(unknown)}'")

    return building

def main():
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser(description='Reads KNX project file and creates an openhab output for things / items / sitemap')
    parser.add_argument("--file_path", type=Path,
                        help='Path to the input knx project.')
    parser.add_argument("--knxPW", type=str, help="Password for knxproj-File if protected")
    parser.add_argument("--readDump", action="store_true", 
                        help="Reading KNX Project from .json Dump") 
    pargs = parser.parse_args()
    if pargs.file_path is None:
        root = tk.Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename()
        if file_path == "":
            raise SystemExit
        pargs.file_path = Path(file_path)
        if pargs.file_path.suffix == ".json":
            pargs.readDump = True

    if pargs.readDump:
        project: KNXProject
        with open(pargs.file_path, encoding="utf-8") as f:
            project = json.load(f)
    else:
        knxproj: XKNXProj = XKNXProj(
            path=pargs.file_path,
            password=pargs.knxPW,  # optional
            language="de-DE",  # optional
        )
        project: KNXProject = knxproj.parse()


    building=createBuilding(project)
    addresses=getAddresses(project)
    house=putAddressesInBuilding(building,addresses)

    ets_to_openhab.house = house[0]["floors"]
    ets_to_openhab.all_addresses = addresses
    ets_to_openhab.main()

if __name__ == "__main__":
    main()
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
unknown_floorname=config['general']['unknown_floorname']
unknown_roomname=config['general']['unknown_roomname']
addMissingItems=config['general']['addMissingItems']

re_item_Room =re.compile(pattern_item_Room)
re_item_Floor =re.compile(pattern_item_Floor)
re_floor_nameshort =re.compile(pattern_floor_nameshort)

def createBuilding(project: KNXProject):
    locations = project['locations']
    if len(locations)==0:
        logging.error("'locations' is Empty.")
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
            logging.debug(f"Added building: {loc['name']}")
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
                logging.debug(f"Added floor: {floor['description']}")
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
                logging.debug(f"Processed floor: {prj_floor['Description']}")
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
                        logging.debug(f"Added room: {room['description']}")
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
                logging.debug(f"Processed room: {prj_room['Description']}")

    # Logging information about the final building structure
    #logging.info(f"Building structure created: {prj}")
    return prj
def getAddresses(project: KNXProject):
    # Extract relevant information from the KNXProject
    group_addresses = project['group_addresses']
    communication_objects = project['communication_objects']
    devices = project['devices']
    group_ranges = project['group_ranges']

    # Check if data is available
    if len(group_addresses) == 0:
        logging.error("'group_addresses' is Empty.")
        raise ValueError("'group_addresses' is Empty.")
    if len(communication_objects) == 0:
        logging.error("'communication_objects' is Empty.")
        raise ValueError("'communication_objects' is Empty.")
    if len(devices) == 0:
        logging.error("'devices' is Empty.")
        raise ValueError("'devices' is Empty.")
    if len(group_ranges) == 0:
        logging.error("'group_ranges' is Empty.")
        raise ValueError("'group_ranges' is Empty.") 
    _addresses = []
    for address in group_addresses.values():
        ignore = False

        # Check for 'ignore' flag in comment
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

            # Process communication objects associated with the address
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

                                # Filter communication objects based on channel
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
                laddress["Floor"]=unknown_floorname
            if resRoom:
                laddress["Room"]=resRoom.group(0)
            else:
                laddress["Room"]=unknown_roomname
            laddress["DatapointType"] = "DPST-{}-{}".format(address["dpt"]["main"],address["dpt"]["sub"])  if address["dpt"]["sub"] else "DPT-{}".format(address["dpt"]["main"]) 

            #logging.debug(f"Processed address: {laddress}")
    return _addresses            
def _getSensorCoFromList(cos):
    """
    Diese Funktion sucht in einer Liste von Kommunikationsobjekten (cos) nach einem Sensor-Kommunikationsobjekt,
    das für das Lesen oder Übertragen (transmit) aktiviert ist.
    
    Args:
        cos (list): Eine Liste von Kommunikationsobjekten.

    Returns:
        dict or None: Das erste gefundene Sensor-Kommunikationsobjekt oder None, wenn keines gefunden wurde.
    """
    # Überprüfen, ob die Kommunikationsobjekte vorhanden sind
    if "communication_object" in cos:
        for co in cos["communication_object"]:
            # Überprüfen, ob das Kommunikationsobjekt Flags enthält
            if "flags" in co:
                # Überprüfen, ob das Flag 'read' aktiviert ist
                if "read" in co["flags"]:
                    if co["flags"]["read"] == True:
                        logging.debug(f"Found sensor communication object for reading: {co['name']}")
                        return co
                # Überprüfen, ob das Flag 'transmit' aktiviert ist
                if "transmit" in co["flags"]:
                    if co["flags"]["transmit"] == True:
                        logging.debug(f"Found sensor communication object for transmitting: {co['name']}")
                        return co
    logging.debug("No sensor communication object found.")
    return None
def putAddressesInBuilding(building,addresses):
    """
    Diese Funktion platziert Adressen in einem Gebäudeobjekt basierend auf den zugehörigen Etagen und Räumen.

    Args:
        building (list): Eine Liste von Gebäudeobjekten.
        addresses (list): Eine Liste von Adressen, die platziert werden sollen.
        addMissingItems (bool): Ein optionaler Parameter, der angibt, ob fehlende Adressen automatisch dem Standard-Platzhalter(unknown_floorname/unknown_roomname) hinzugefügt werden sollen. Standardmäßig True.

    Returns:
        list: Das aktualisierte Gebäudeobjekt.
    """    
    if len(building)==0:
        raise ValueError("'building' is Empty.")
    if len(addresses)==0:
        raise ValueError("'addresses' is Empty.")
    # Liste für unbekannte Adressen initialisieren
    unknown =[]
    for address in addresses:
        found=False
        # Versuche, das Sensor-Kommunikationsobjekt für das Lesen zu erhalten
        read_co = _getSensorCoFromList(address)

        # Durchlaufe jedes Gebäudeobjekt
        for itembuilding in building:
            for floor in itembuilding["floors"]:
                # Überprüfe, ob die Etage der Adresse entspricht
                if floor["name_short"] == address["Floor"]:
                    for room in floor["rooms"]:
                        # Überprüfe, ob der Raum der Adresse entspricht
                        if room["name_short"] == address["Room"]:
                            # Füge die Adresse dem Raum hinzu
                            if not "Addresses" in room:
                                room["Addresses"]=[]
                            room["Addresses"].append(address)
                            logger.info(f"Address {address['Address']} placed in Room: {room['name_short']}, Floor: {floor['name_short']}")
                            found=True
                            break
        # Wenn Adresse nicht in Etagen und Räumen gefunden wurde und ein Sensor-Kommunikationsobjekt vorhanden ist
        if not found:
            if read_co:
                # Durchlaufe erneut jede Etage und Raum
                for floor in itembuilding["floors"]:
                    for room in floor["rooms"]:
                        # Überprüfe, ob der Raum ein Gerät mit dem Sensor-Kommunikationsobjekt enthält
                        if 'devices' in room:
                            if read_co['device_address'] in room['devices']:
                                 # Füge die Adresse dem Raum hinzu
                                 room["Addresses"].append(address)
                                 found=True
                                 logger.info(f"Address {address['Address']} placed in Room (via device association): {room['name_short']}, Floor: {floor['name_short']}")
                                 break
        if not found:
            unknown.append(address)
    if addMissingItems:
        # Füge eine Standardetage und einen Standardraum hinzu
        building[0]["floors"].append({
                    'Description':unknown_floorname,
                    'Group name':unknown_floorname,
                    'name_long':unknown_floorname,
                    'name_short':unknown_floorname,
                    'rooms':[]
                    })
        building[0]["floors"][-1]["rooms"].append({
                            'Description':unknown_roomname,
                            'Group name':unknown_roomname,
                            'name_long':unknown_roomname,
                            'name_short':unknown_roomname,
                            'Addresses':[]
                        })
        # Füge die unbekannten Adressen dem Standardraum hinzu
        building[0]["floors"][-1]["rooms"][-1]["Addresses"]=unknown
        logger.info(f"Added default Floor and Room for unknown addresses: {unknown_floorname}, {unknown_roomname}")
    else:
        if unknown:
            logger.info(f"Unknown addresses: {unknown}")
        logger.info(f"Total unknown addresses: {len(unknown)}")

    return building

def main():
     # Konfiguration des Logging-Levels auf DEBUG
    logging.basicConfig(level=logging.DEBUG)

    # Argumentenparser erstellen
    parser = argparse.ArgumentParser(description='Reads KNX project file and creates an openhab output for things / items / sitemap')
    parser.add_argument("--file_path", type=Path,
                        help='Path to the input knx project.')
    parser.add_argument("--knxPW", type=str, help="Password for knxproj-File if protected")
    parser.add_argument("--readDump", action="store_true", 
                        help="Reading KNX Project from .json Dump") 
    pargs = parser.parse_args()

    # Überprüfen, ob ein Dateipfad angegeben wurde, sonst den Benutzer nach einer Datei fragen
    if pargs.file_path is None:
        root = tk.Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename()
        if file_path == "":
            raise SystemExit
        pargs.file_path = Path(file_path)
        if pargs.file_path.suffix == ".json":
            pargs.readDump = True

    # KNX-Projekt einlesen (entweder aus .knxproj-Datei oder aus .json-Dump)
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

    # Gebäude erstellen
    building=createBuilding(project)
    # Adressen extrahieren
    addresses=getAddresses(project)
    # Adressen im Gebäude platzieren
    house=putAddressesInBuilding(building,addresses)

    # Konfiguration für OpenHAB setzen
    ets_to_openhab.house = house[0]["floors"]
    ets_to_openhab.all_addresses = addresses
    # OpenHAB-Konvertierung durchführen
    logging.info("Calling ets_to_openhab.main()")
    ets_to_openhab.main()

if __name__ == "__main__":
    main()
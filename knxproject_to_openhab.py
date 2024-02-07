#pip install xknxproject
#pip install git+https://github.com/XKNX/xknxproject.git

"""Extract and parse a KNX project file."""
import logging
import re
import json
import argparse
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from xknxproject.models import KNXProject
from xknxproject import XKNXProj
from config import config

import ets_to_openhab

logger = logging.getLogger(__name__)

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

def create_building(project: KNXProject):
    """Creats an Building with all Floors and Rooms"""
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
            logging.debug("Added building: %s",loc['name'])
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
                logging.debug("Added floor: %s %s",floor['description'],floor['name'])
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
                logging.debug("Processed floor: %s",prj_floor['Description'])
                for room in floor['spaces'].values():
                    if room['type'] in ('Room','Corridor','Stairway'):
                        prj_floor['rooms'].append({
                            'Description':room['description'],
                            'Group name':None,
                            'name_long':room['description'],
                            'name_short':None,
                            'devices':room['devices'],
                            'Addresses':[]
                        })
                        prj_room=prj_floor['rooms'][-1]
                        logging.debug("Added room: %s %s",room['description'],room['name'])
                        res_floor = re_item_Floor.search(room['name'])
                        res_room = re_item_Room.search(room['name'])
                        room_nameplain = room['name']
                        room_namelong = ''
                        if res_floor is not None:
                            room_namelong+=res_floor.group(0)
                            room_nameplain=str.replace(room_nameplain,res_floor.group(0),"").strip()
                            if prj_floor['name_short']==floor['name'] or prj_floor['name_short']==item_Floor_nameshort_prefix+floor['name']:
                                prj_floor['name_short']=res_floor.group(0)
                                prj_floor['Description']=str.replace(floor['name'],res_floor.group(0),"").strip()
                        else:
                            if not prj_floor['name_short'] == '':
                                room_namelong+=prj_floor['name_short']
                            else:
                                room_namelong+=item_Floor_nameshort_prefix+'XX'
                        if res_room is not None:
                            room_namelong+=res_room.group(0)
                            room_nameplain=str.replace(room_nameplain,res_room.group(0),"").strip()
                            prj_room['name_short']=res_room.group(0)
                        else:
                            prj_room['name_short']=item_Room_nameshort_prefix+'RMxx'
                            room_namelong+=item_Room_nameshort_prefix+'RMxx'
                        if room_nameplain == '':
                            room_nameplain=room['usage_text']
                        prj_room['Description']=room_nameplain
                        if prj_room['name_long'] == '':
                            prj_room['name_long']=room_namelong
                        if not prj_room['Group name']:
                            prj_room['Group name']=prj_room['name_short']
                if prj_floor['name_long'] == '':
                    prj_floor['name_long']=prj_floor['name_short']
                if not prj_floor['Group name']:
                    prj_floor['Group name']=prj_floor['name_short']
                logging.debug("Processed room: %s",prj_room['Description'])

    # Logging information about the final building structure
    #logging.info(f"Building structure created: {prj}")
    return prj
def get_addresses(project: KNXProject):
    """
    Extracts and processes information from a KNX project.

    Args:
        project (KNXProject): An object representing a KNX project.

    Returns:
        List[Dict[str, Any]]: A list of dictionaries containing processed information
        for each group address, including details on communication objects, devices,
        floor, room, and datapoint type.
        
    Raises:
        ValueError: If essential data structures (group_addresses, communication_objects,
        devices, group_ranges) are empty.
    """
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
        if address['address']=='6/1/0':
            logger.warning("Breakpoint!!!")
        ignore = False

        # Check for 'ignore' flag in comment
        if 'ignore' in address['comment']:
            logger.info("Ignore: %s",address['name'])
            ignore = True
        elif not address['communication_object_ids']:
            logger.info("Ignore: %s because no communication object connected",address['name'])
            ignore = True
        else:
            res_room = re_item_Room.search(address['name'])
            res_floor = re_item_Floor.search(address['name'])

            if not res_floor:
                address_split = address['address'].split("/")
                gr_top =group_ranges.get(address_split[0])
                gr_middle =gr_top['group_ranges'].get(address_split[0] + "/" + address_split[1])
                res_floor = re_item_Floor.search(gr_middle['name'])
                if not res_floor:
                    res_floor = re_item_Floor.search(gr_top['name'])
                    if not res_floor:
                        res_floor = re_floor_nameshort.search(gr_middle['name'])
                        if not res_floor:
                            res_floor = re_floor_nameshort.search(gr_top['name'])
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
            if res_floor:
                laddress["Floor"]=res_floor.group(0)
                if not laddress["Floor"].startswith(item_Floor_nameshort_prefix) and len(laddress["Floor"]) < 6:
                    laddress["Floor"]=item_Floor_nameshort_prefix+laddress["Floor"]
            else:
                laddress["Floor"]=unknown_floorname
            if res_room:
                laddress["Room"]=res_room.group(0)
            else:
                laddress["Room"]=unknown_roomname
            laddress["DatapointType"] = f'DPST-{address["dpt"]["main"]}-{address["dpt"]["sub"]}' if address["dpt"]["sub"] else f'DPT-{address["dpt"]["main"]}'

            #logging.debug(f"Processed address: {laddress}")
    return _addresses
def _get_sensor_co_from_list(cos):
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
                    if co["flags"]["read"]:
                        logging.debug("Found sensor communication object for reading: %s",co['name'])
                        return co
                # Überprüfen, ob das Flag 'transmit' aktiviert ist
                if "transmit" in co["flags"]:
                    if co["flags"]["transmit"]:
                        logging.debug("Found sensor communication object for transmitting: %s",co['name'])
                        return co
    logging.debug("No sensor communication object found.")
    return None
def put_addresses_in_building(building,addresses):
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
        read_co = _get_sensor_co_from_list(address)

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
                            logger.info("Address %s placed in Room: %s, Floor: %s",address['Address'],room['name_short'],floor['name_short'])
                            found=True
                            break
        # Wenn Adresse nicht in Etagen und Räumen gefunden wurde und ein Sensor-Kommunikationsobjekt vorhanden ist
        if not found:
            if read_co:
                # Durchlaufe erneut jedes Gebäudeobjekt, Etage und Raum
                for itembuilding in building:
                    for floor in itembuilding["floors"]:
                        for room in floor["rooms"]:
                            # Überprüfe, ob der Raum ein Gerät mit dem Sensor-Kommunikationsobjekt enthält
                            if 'devices' in room:
                                if read_co['device_address'] in room['devices']:
                                    # Füge die Adresse dem Raum hinzu
                                    room["Addresses"].append(address)
                                    found=True
                                    logger.info("Address %s placed in Room (via device association): %s, Floor: %s",address['Address'],room['name_short'],floor['name_short'])
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
        logger.info("Added default Floor and Room for unknown addresses: %s, %s",unknown_floorname,unknown_roomname)
    else:
        if unknown:
            logger.info("Unknown addresses: %s",unknown)
        logger.info("Total unknown addresses: %s",len(unknown))

    return building
def create_json_dump(project: KNXProject,file_path: Path):
    '''Create Json Dump from KNXproject File '''
    #os.makedirs(os.path.dirname("tests"), exist_ok=True)
    with open(f"tests/{file_path.name}.json", "w", encoding="utf8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)
def _get_gwip(project: KNXProject):
    devices = project['devices']
    # Check if data is available
    if len(devices) == 0:
        logging.error("'devices' is Empty.")
        raise ValueError("'devices' is Empty.")
    for device in devices:
        if devices[device]['hardware_name'] in config['devices']['gateway']['hardware_name']:
            description = devices[device]['description']
            ip = re.search(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}',description).group()
            return ip
    return None
def main():
    """Main function"""
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
        # Erstelle ein JSON Dump des aktuellen Projekts
        create_json_dump(project,pargs.file_path)

    # Gebäude erstellen
    building=create_building(project)
    # Adressen extrahieren
    addresses=get_addresses(project)
    # Adressen im Gebäude platzieren
    house=put_addresses_in_building(building,addresses)
    ip=_get_gwip(project)

    # Konfiguration für OpenHAB setzen
    ets_to_openhab.house = house[0]["floors"]
    ets_to_openhab.all_addresses = addresses
    ets_to_openhab.gwip=ip
    # OpenHAB-Konvertierung durchführen
    logging.info("Calling ets_to_openhab.main()")
    ets_to_openhab.main()

if __name__ == "__main__":
    main()

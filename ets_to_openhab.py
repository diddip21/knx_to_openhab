"""Module providing a collection of function to generate openhab things/items/sitemap from a knxproject"""
import csv
import re
import os
import logging
from config import config,normalize_string
logger = logging.getLogger(__name__)

pattern_items_Name=config['regexpattern']['items_Name']
pattern_items_Label=config['regexpattern']['items_Label']

def data_of_name(data, name, suffix,replace=''):
    """ Function get data from a Name"""
    if isinstance(suffix, str):
        suffix= [suffix,]
    if isinstance(replace, str):
        replace= [replace,]
    for x in data:
        if x['Group name'] == name:
            continue
        for s in suffix:
            if x['Group name'] == name + s:
                return x
            if x['Group name'] == name + ' ' + s:
                return x
            for r in replace:
                if x['Group name'] == name.replace(r,s):
                    return x
    return None

#global house,all_addresses,used_addresses
gwip=None
house = []
all_addresses = []
export_to_influx = []
used_addresses = []
items = ''
equipments={}
sitemap = ''
things = ''
semantic_things = ''
selections = ''
semantic_cnt = 0
fensterkontakte = []
cnt = 0

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

def read_csvexport():
    """Reads an ETS csv Export"""
    csvfile = open(config['ets_export'], newline='', encoding='cp1252')
    reader = csv.DictReader(csvfile, delimiter='\t')

    for row in reader:
        #print(row)
        # check if floor:
        if row['Address'].endswith('/-/-'):
            if not 'Group name' in row:
                row['Group name'] = row['Main']
            row['rooms'] = []
            house.insert(int(row['Address'].split('/')[0]),row)
            #house[int(row['Address'].split('/')[0])] = row
        # check if room
        elif row['Address'].endswith('/-'):
            if not 'Group name' in row:
                row['Group name'] = row['Middle']
            splitter = row['Address'].split('/')
            row['Addresses'] = []
            house[int(splitter[0])]['rooms'].insert(int(splitter[1]),row)
        # normal group address
        else:
            if not 'Group name' in row:
                row['Group name'] = row['Sub']
            splitter = row['Address'].split('/')
            if 'ignore' in row['Description']:
                logger.debug("ignoreflag in description for: %s", row['Group name'])
                continue
            house[int(splitter[0])]['rooms'][int(splitter[1])]['Addresses'].append(row)
            all_addresses.append(row)

def gen_building():
    """Generates a Building from an ETS Project"""
    def get_co_by_functiontext(cos,config_functiontexts,checkwriteflag=True):
        """
        Diese Funktion sucht in einer Liste von Kommunikationsobjekten (cos) nach einem bestimmten Funktions-Text.

        Args:
            cos (list): Eine Liste von Kommunikationsobjekten.
            config_functiontexts (list): Eine Liste von Funktions-Texten, die gesucht werden sollen.
            checkwriteflag (bool): Ein optionaler Parameter, der angibt, ob das 'write'-Flag überprüft werden soll. Standardmäßig True.

        Returns:
            dict or None: Das gefundene Kommunikationsobjekt oder None, wenn keines gefunden wurde.
        """
        # Überprüfen, ob Kommunikationsobjekte vorhanden sind
        if "communication_object" in cos:
            for co in cos["communication_object"]:
                # Überprüfen, ob das 'write'-Flag überprüft werden soll und ob es aktiviert ist
                if checkwriteflag:
                    if "flags" in co:
                        if "write" in co["flags"]:
                            if not co["flags"]["write"]:
                                continue
                # Überprüfen, ob der Funktions-Text in der Konfiguration vorhanden ist
                if normalize_string(co["function_text"]) in config_functiontexts:
                    return co
        return None
    def get_address_from_dco(co,config_functiontexts):
        """
        Diese Funktion sucht in einem Kommunikationsobjekt (co) nach einem Funktions-Text und filtert nach Gruppenzugehörigkeit entweder über die Channels oder über den 'text'.

        Args:
            co (dict): Ein einzelnes Kommunikationsobjekt.
            config_functiontexts (list): Eine Liste von Funktions-Texten, die gesucht werden sollen.

        Returns:
            dict or None: Das gefundene Kommunikationsobjekt oder None, wenn keines gefunden wurde.
        """
        # Verwende "channel" für die Gruppierung oder alternativ "text"
        if "channel" in co:
            group_channel = co["channel"]
        if "text" in co:
            group_text = co["text"]
        # Überprüfen, ob "device_communication_objects" im Kommunikationsobjekt vorhanden ist
        if "device_communication_objects" in co:
            for y in co["device_communication_objects"]:
                # Überprüfen, ob der Kanal übereinstimmt (falls vorhanden)
                if group_channel:
                    if group_channel != y["channel"]:
                        continue
                else:
                    # Überprüfen, ob der Text übereinstimmt (falls vorhanden)
                    if group_text:
                        if group_text != y["text"]:
                            continue
                # Überprüfen, ob der Funktions-Text in der Konfiguration vorhanden ist
                if normalize_string(y["function_text"]) in config_functiontexts:
                    # Suche nach der Adresse, die mit den Gruppenadressen verknüpft ist
                    search_address = [x for x in all_addresses if x["Address"] in y['group_address_links']]
                    # Wenn genau eine Adresse gefunden wurde, gib sie zurück
                    if len(search_address)==1:
                        return search_address[0]
                    # Wenn mehrere Adressen gefunden wurden, wähle die mit den wenigsten Kommunikationsobjekten
                    elif len(search_address) > 1:
                        lowlenco = 99
                        lowco=None
                        for sa in search_address:
                            if "communication_object" in sa:
                                if len(sa["communication_object"]) < lowlenco:
                                    lowlenco=len(sa["communication_object"])
                                    lowco = sa
                        return lowco
        return None
    global items,sitemap,things
    floor_nr=0
    for floor in house:
        floor_nr+=1
        floor_name = floor['Group name']
        if config['general']['FloorNameFromDescription'] and floor['Description'] != '':
            floor_name = floor['Description']
        descriptions = floor['Description'].split(';')
        visibility = ''
        semantic = '["Location"]'
        synonyms = ''
        icon = ''
        for description in descriptions:
            if description == 'debug':
                visibility = 'visibility=[extended_view==ON]'
            if description.startswith('icon='):
                icon = '<' + description.replace('icon=','') + '>'
            if description.startswith('semantic='):
                semantic = '["Location", "' + description.replace('semantic=','').replace(',','","') + '"] '
            if description.startswith('synonyms='):
                synonyms = '{ ' + description.replace('synonyms=','synonyms="').replace(',',', ') + '" } '

        items += f"Group   map{floor_nr}   \"{floor_name}\" {icon}  {semantic} {synonyms} \n" # {location}  \n" # {visibility}
        sitemap += f"Frame label=\"{floor_name}\" {{\n"
        room_nr=0
        logger.debug("Floor: %s",floor_name)
        for room in floor['rooms']:
            room_nr+=1
            room_name = room['Group name']
            # Überprüfe, ob der Raumname aus der Beschreibung genommen werden soll
            if config['general']['RoomNameFromDescription'] and room['Description'] != '':
                room_name = room['Description']
            room_nameoriginal = room_name
            descriptions = room['Description'].split(';')
            visibility = ''
            semantic = f"[\"Location\", \"Room\", \"{room_name}\"]"
            icon = ''
            synonyms = ''
            for description in descriptions:
                if description == 'debug':
                    visibility = 'visibility=[extended_view==ON]'
                if description.startswith('icon='):
                    icon = '<' + description.replace('icon=','') + '>'
                if description.startswith('semantic='):
                    semantic = '["Location", "' + description.replace('semantic=','').replace(',','","') + '"] '
                if description.startswith('synonyms='):
                    synonyms = '{ ' + description.replace('synonyms=','synonyms="').replace(',',', ') + '" } '
                if description.startswith('name='):
                    room_name = description.replace('name=','')

            items += f"Group   map{floor_nr}_{room_nr}   \"{room_name}\"  {icon}  (map{floor_nr})   {semantic} {synonyms}\n"
            sitemap += f"     Group item=map{floor_nr}_{room_nr} {visibility} label=\"{room_name}\" "
            group = ""

            addresses = room['Addresses']
            logger.debug("Room: %s and %s Adresses",room_name,len(addresses))
            # the loop has to be executed twice.
            # - during the first run, all GAs are processed which can have a reference to another GA (e.g. a switch with status feedback)
            #   and also all GAs which can not have a reference to another GA. (e.g. temperatures)
            # - during the second run, all not marked componentes are processed directly with no reference check
            for run in range(2):
                for i in range(len(addresses)):

                    address = room['Addresses'][i]
                    # in the second run: only process not already used addresses
                    #if run > 0:
                    if not any(item['Address'] == address['Address'] for item in all_addresses):
                    #if address['Address'] not in all_addresses:
                        continue
                    if address['Address'] == '1/0/10':
                        logger.debug("Adress found - Breakpoint?")

                    used = False
                    auto_add = False
                    item_icon = None
                    co=None
                    sitemap_type = 'Default'
                    mappings = ''
                    metadata = ''
                    semantic_info=''
                    #lovely_name = ' '.join(address['Group name'].replace(house[floor_nr]['rooms'][room_nr]['Group name'],'').replace(house[floor_nr]['Group name'],'').split())
                    lovely_name = address['Group name']
                    item_label = lovely_name
                    descriptions = address['Description'].split(';')
                    equipment = ''
                    define=None

                    #print(f"--- processing: {lovely_name}")
                    #print(address)

                    if 'IGNORE' in address.keys():
                        continue

                    shortened_name = ' '.join(address['Group name'].replace(room['Group name'],'').replace(floor['Group name'],'').split())
                    item_name = f"i_{cnt}_{floor['Group name']}_{room['Group name']}_{shortened_name}"
                    item_name = item_name.translate(config['special_char_map'])
                    item_name = re.sub(pattern_items_Name, '', item_name)
                    if run == 0:
                        # dimmer
                        if address['DatapointType'] == 'DPST-5-1':
                            define=config['defines']['dimmer']
                            #bol = [x for x in define['absolut_suffix'] if x in address['Group name']]
                            co = get_co_by_functiontext(address,define['absolut_suffix'])
                            if not co:
                                continue

                            basename = address['Group name']
                            #dimmwert_status =data_of_name(all_addresses, basename, define['status_suffix'],define['absolut_suffix'])
                            #if not dimmwert_status and co:
                            dimmwert_status=get_address_from_dco(co,define['status_suffix'])
                            for drop_name in define['drop']:
                                drop_addr = data_of_name(all_addresses, basename, drop_name,define['absolut_suffix'])
                                if drop_addr:
                                    used_addresses.append(drop_addr['Address'])
                            relative_option=''
                            switch_option = ''
                            switch_option_status = ''
                            if dimmwert_status:
                                used = True
                                used_addresses.append(dimmwert_status['Address'])
                                #relative_command = data_of_name(all_addresses, basename, define['relativ_suffix'],define['absolut_suffix'])
                                #if not relative_command and co:
                                relative_command=get_address_from_dco(co,define['relativ_suffix'])
                                #switch_command = data_of_name(all_addresses, basename, define['switch_suffix'],define['absolut_suffix'])
                                #if not switch_command and co:
                                if relative_command:
                                    used_addresses.append(relative_command['Address'])
                                    relative_option = f", increaseDecrease=\"{relative_command['Address']}\""
                                switch_command=get_address_from_dco(co,define['switch_suffix'])
                                if switch_command:
                                    used_addresses.append(switch_command['Address'])
                                    #switch_status_command = data_of_name(all_addresses, basename, define['switch_status_suffix'],define['absolut_suffix'])
                                    #if not switch_status_command and co:
                                    switch_status_command=get_address_from_dco(co,define['switch_status_suffix'])
                                    if switch_status_command:
                                        used_addresses.append(switch_status_command['Address'])
                                        switch_option_status = f"+<{switch_status_command['Address']}"
                                    switch_option = f", switch=\"{switch_command['Address']}{switch_option_status}\""
                                #lovely_name = ' '.join(lovely_name.replace('Dimmen','').replace('Dimmer','').replace('absolut','').replace('Licht','').split())

                                auto_add = True
                                item_type = "Dimmer"
                                thing_address_info = f"position=\"{address['Address']}+<{dimmwert_status['Address']}\"{switch_option}{relative_option}"
                                #item_label = f"{lovely_name} [%d %%]"
                                equipment = 'Lightbulb'
                                semantic_info = "[\"Light\"]"
                                item_icon = "light"
                            else:
                                logger.warning("incomplete dimmer: %s / %s",basename,address['Address'])

                        # rollos / jalousien
                        elif address['DatapointType'] == 'DPST-1-8':
                            define=config['defines']['rollershutter']
                            #bol = [x for x in define['up_down_suffix'] if x in address['Group name']]
                            co = get_co_by_functiontext(address,define['up_down_suffix'])
                            if not co:
                                continue

                            basename = address['Group name'] #.replace(define['up_down_suffix'],'')
                            fahren_auf_ab = address
                            #Status Richtung nicht in verwendung durch openhab
                            for drop_name in define['drop']:
                                drop_addr = data_of_name(all_addresses, basename, drop_name,define['up_down_suffix'])
                                if drop_addr:
                                    used_addresses.append(drop_addr['Address'])
                            option_stop =''
                            option_position=''
                            option_position_absolute=''
                            option_position_status=''
                            if fahren_auf_ab:
                                used_addresses.append(fahren_auf_ab['Address'])
                                #fahren_stop = data_of_name(all_addresses, basename, define['stop_suffix'],define['up_down_suffix'])
                                #if not fahren_stop and co:
                                fahren_stop=get_address_from_dco(co,define['stop_suffix'])
                                if fahren_stop:
                                    used_addresses.append(fahren_stop['Address'])
                                    option_stop = f", stopMove=\"{fahren_stop['Address']}\""
                                #absolute_position = data_of_name(all_addresses, basename, define['absolute_position_suffix'],define['up_down_suffix'])
                                #if not absolute_position and co:
                                absolute_position=get_address_from_dco(co,define['absolute_position_suffix'])
                                #absolute_position_status = data_of_name(all_addresses, basename, define['status_suffix'],define['up_down_suffix'])
                                #if not absolute_position_status and co:
                                absolute_position_status=get_address_from_dco(co,define['status_suffix'])
                                if absolute_position or absolute_position_status:
                                    if absolute_position:
                                        used_addresses.append(absolute_position['Address'])
                                        option_position_absolute =f"{absolute_position['Address']}"
                                    if absolute_position_status:
                                        used_addresses.append(absolute_position_status['Address'])
                                        if absolute_position:
                                            option_position_status = f"+<{absolute_position_status['Address']}"
                                        else:
                                            option_position_status = f"<{absolute_position_status['Address']}"
                                    option_position = f", position=\"{option_position_absolute}{option_position_status}\""

                                auto_add = True
                                item_type = "Rollershutter"
                                thing_address_info = f"upDown=\"{fahren_auf_ab['Address']}\"{option_stop}{option_position }"
                                #item_label = f"{lovely_name} [%d %%]"
                                equipment = 'Blinds'
                                semantic_info = "[\"Blinds\"]"
                                item_icon = "rollershutter"
                            else:
                                logger.warning("incomplete rollershutter: %s",basename)

                        # Heizung
                        elif address['DatapointType'] in ('DPST-5-010','DPST-20-102'):
                            define=config['defines']['heating']
                            #bol = [x for x in define['level_suffix'] if x in address['Group name']]
                            co = get_co_by_functiontext(address,define['level_suffix'])
                            if  not co:
                                continue
                            basename = address['Group name'] #.replace(define['up_down_suffix'],'')
                            betriebsmodus = address
                            option_status_betriebsmodus=''
                            if betriebsmodus:
                                used_addresses.append(betriebsmodus['Address'])
                                #betriebsmodus_status = data_of_name(all_addresses, basename, define['status_level_suffix'],define['level_suffix'])
                                #if not betriebsmodus_status and co:
                                betriebsmodus_status=get_address_from_dco(co,define['status_level_suffix'])
                                if betriebsmodus_status:
                                    used_addresses.append(betriebsmodus_status['Address'])
                                    option_status_betriebsmodus = f"+<{betriebsmodus_status['Address']}"
                                auto_add = True
                                item_type = "Number:Dimensionless"
                                ga = "5.010"
                                if address['DatapointType'] == 'DPST-20-102':
                                    item_type = "Number"
                                    ga="20.102"
                                thing_address_info = f"ga=\"{ga}:{address['Address']}{option_status_betriebsmodus}\""
                                item_label = f"{lovely_name}"
                                equipment = 'HVAC'
                                semantic_info = "[\"HVAC\"]"
                                item_icon = "heating_mode"
                                metadata=', stateDescription=\"\"[options=\"NULL=unbekannt ...,1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"], commandDescription=\"\"[options=\"1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"], listWidget=\"\"[iconUseState=\"true\"]'

                            else:
                                logger.warning("incomplete heating: %s",basename)

                    #  erst im zweiten durchlauf prüfen damit integrierte Schaltobjekte (z.B. dimmen) vorher schon erkannt werden.
                    if run > 0:
                        # Schalten or bool
                        if address['DatapointType'] == 'DPST-1-1' or address['DatapointType'] == 'DPST-1-2':
                            define=config['defines']['switch']
                            item_type = "Switch"
                            item_label = lovely_name
                            # umschalten (Licht, Steckdosen)
                            # only add in first round, if there is a status GA for feedback
                            #bol = [x for x in define['switch_suffix'] if x in address['Group name']]
                            co = get_co_by_functiontext(address,define['switch_suffix'])
                            if  not co:
                                continue

                            basename = address['Group name']
                            #status =data_of_name(all_addresses, basename, define['status_suffix'],define['switch_suffix'])
                            #if not status and co:
                            status=get_address_from_dco(co,define['status_suffix'])
                            if status:
                                #if status['DatapointType'] == 'DPST-1-11':
                                auto_add = True
                                used_addresses.append(status['Address'])
                                thing_address_info = f"ga=\"{address['Address']}+<{status['Address']}\""
                            else:
                                auto_add = True
                                thing_address_info = f"ga=\"{address['Address']}\""
                                semantic_info = "[\"Control\", \"Switch\"]"
                                item_icon = "switch"


                    ######## determined only by datapoint
                    # do this only after items with multiple addresses are processed:
                    # e.g. the state datapoint could be an own thing or the feedback from a switch or so
                    if run > 0:
                        # Iterate über die Mappings
                        for datapoint_type, mapping_info in datapoint_mappings.items():
                            if address['DatapointType'] == datapoint_type:
                                auto_add = True
                                item_type = mapping_info['item_type']
                                if item_type.casefold() in config['defines']:
                                    define = config['defines'][item_type.casefold()]
                                thing_address_info = f"ga=\"{mapping_info['ga_prefix']}:{address['Address']}\""
                                if "=" in mapping_info['ga_prefix']:
                                    split_info=mapping_info['ga_prefix'].split("=")
                                    thing_address_info = f"{split_info[0]}=\"{split_info[1]}:{address['Address']}\""
                                item_label = f"{lovely_name}"
                                metadata=f"{mapping_info['metadata']}"
                                semantic_info = f"{mapping_info['semantic_info']}"
                                item_icon = mapping_info['item_icon']
                                if 'Soll' in lovely_name:
                                    semantic_info = semantic_info.replace("Measurement","Setpoint")
                                break
                        # window/door
                        if address['DatapointType'] == 'DPST-1-19':
                            equipment = 'Window'
                            fensterkontakte.append({'item_name': item_name, 'name': address['Group name']})

                        # Szene
                        if address['DatapointType'] in ('DPST-17-1','DPST-18-1'):
                            used = True
                            ga = "17.001"
                            if address['DatapointType'] == 'DPST-18-1':
                                ga="18.001"

                            for description in descriptions:
                                if '=' in description:
                                    mappings = description
                                    break

                            if mappings!= '':
                                data_map = mappings.replace("'",'"').replace('"','').replace('=','.0=')
                                metadata=f', stateDescription=\"\"[options=\"NULL=unbekannt ...,{data_map}\"], commandDescription=\"\"[options=\"{data_map}\"]'
                                item_label = lovely_name
                                #TODO: Mappings noch über metadata abbilden
                                #mapfile = f"gen_{item_name}.map"
                                #mappings = mappings.replace("'",'"')

                                #mapfile_content = mappings.replace('"','').replace(',','\n').replace('mappings=[','').replace(']','').replace(' ','')
                                #mapfile_content += '\n' + mapfile_content.replace('=','.0=') + '\n-=unknown'
                                #os.makedirs(os.path.realpath(config['transform_dir_path']), exist_ok=True)
                                #open(os.path.join(config['transform_dir_path'], mapfile),'w', encoding='utf8').write(mapfile_content)

                                auto_add = True
                                item_type = "Number"
                                thing_address_info = f"ga=\"{ga}:{address['Address']}\""
                                #item_label = f"{lovely_name} [MAP({mapfile}):%s]"
                                semantic_info = "[\"Equipment\"]"
                                item_icon = "movecontrol"
                                sitemap_type = "Selection"
                            else:
                                logger.info("no mapping for scene %s %s",address['Address'], address['Group name'])
                            #else:
                            #    items += f"Number        {item_name}         \"{lovely_name} [%d]\"                <movecontrol>          {{ channel=\"knx:device:bridge:generic:{item_name}\" }}\n"
                            #    group += f"        Selection item={item_name} label=\"{lovely_name}\"  {visibility}\n"

                        # Szenensteuerung
                        #if address['DatapointType'] == 'DPST-18-1':
                        #    print(address)
                        #    used = True
                        #    things += f"Type number        : {item_name}        \"{address['Group name']}\"       [ ga=\"18.001:{address['Address']}\" ]\n"
                        #    items += f"Number        {item_name}         \"{lovely_name} [%d]\"                <sun>  (map{floor_nr}_{room_nr})        {{ channel=\"knx:device:bridge:generic:{item_name}\" }}\n"

                    # TODO: get rid of this
                    if define and 'change_metadata' in define:
                        for item in define['change_metadata']:
                            if item in address['Group name']:
                                for var in define['change_metadata'][item]:
                                    match var:
                                        case 'semantic_info':
                                            semantic_info = define['change_metadata'][item][var]
                                        case 'item_icon':
                                            item_icon = define['change_metadata'][item][var]

                    if used:
                        used_addresses.append(address['Address'])

                    if auto_add:
                        used_addresses.append(address['Address'])
                        visibility = ''
                        for description in descriptions:
                            if 'debug' in description:
                                visibility = 'visibility=[extended_view==ON]'
                            if description.startswith('semantic='):
                                semantic_info = '["' + description.replace('semantic=','').replace(',','","') + '"] '
                            if description.startswith('icon='):
                                item_icon = description.replace('icon=','').replace(',','","')
                            if description.startswith('synonyms='):
                                synonyms = '{ ' + description.replace('synonyms=','synonyms="').replace(',',', ') + '" } '
                            if description.startswith('name='):
                                item_label = description.replace('name=','')
                        # remove generic description if unneccessary
                        item_label_short = item_label
                        for drop in config['defines']['drop_words']:
                            item_label_short = item_label_short.replace(drop,'')
                        # remvoe floor and room from label
                        if floor['name_short']:
                            item_label_short=item_label_short.replace(floor['name_short'],'')
                        if room['name_short']:
                            item_label_short=item_label_short.replace(room['name_short'],'')
                        # remove text by item_label pattern
                        item_label_short = re.sub(pattern_items_Label, '', item_label_short)
                        item_label_short=item_label_short.replace('|',' ')
                        #item_label_short = ' '.join(item_label_short.split())
                        if item_label_short != '':
                            item_label = item_label_short

                        if item_icon:
                            item_icon = f"<{item_icon}>"
                        else:
                            item_icon = ""

                        item_label = item_label.replace(room_nameoriginal, room_name)
                        item_label = re.sub(r'\[.*\]', '', item_label)
                        item_label = re.sub(r'\|.*\:', '', item_label)
                        item_label = item_label.strip()

                        thing_type = item_type.lower().split(":")[0]
                        things += f"Type {thing_type}    :   {item_name}   \"{address['Group name']}\"   [ {thing_address_info} ]\n"

                        root = f"map{floor_nr}_{room_nr}"
                        if equipment != '':
                            if not item_label in equipments.keys():
                                equipments[item_label]=item_name
                                items += f"Group   equipment_{item_name}   \"{item_label}\"  {item_icon}  ({root})   [\"{equipment}\"]\n"
                                root = f"equipment_{item_name}"
                            else:
                                root = f"equipment_{equipments[item_label]}"
                        if item_label in equipments.keys():
                            root = f"equipment_{equipments[item_label]}"

                        items += f"{item_type}   {item_name}   \"{item_label}\"   {item_icon}   ({root})   {semantic_info}    {{ channel=\"knx:device:bridge:generic:{item_name}\" {metadata}{synonyms} }}\n"
                        group += f"        {sitemap_type} item={item_name} label=\"{item_label}\" {visibility}\n"

                        if 'influx' in address['Description']:
                            #print('influx @ ')
                            #print(address)
                            export_to_influx.append(item_name)
                    while used_addresses:
                        a = used_addresses.pop()
                        found_item = next((item for item in all_addresses if item['Address'] == a), None)
                        if found_item:
                            all_addresses.remove(found_item)

            if group != '':
                sitemap += f" {{\n{group}\n    }}\n"
            else:
                sitemap += "\n "
        sitemap += "}\n "

def check_unused_addresses():
    """Logs all unused addresses for further manual actions"""
    # process all addresses which were not used
    for address in all_addresses:
        logger.info("unused: %s: %s with type %s",address['Address'],address['Group name'],address['DatapointType'])

def export_output():
    """Exports things / items / sitemap / ...  Files"""
    global items,sitemap,things

    # export things:
    things_template = open('things.template','r', encoding='utf8').read()
    if gwip:
        things_template = things_template.replace('###gwip###', gwip)
    things = things_template.replace('###things###', things)
    os.makedirs(os.path.dirname(config['things_path']), exist_ok=True)
    open(config['things_path'],'w', encoding='utf8').write(things)
    # export items:
    items_template =  open('items.template','r', encoding='utf8').read()
    items = items_template.replace('###items###', items)
    os.makedirs(os.path.dirname(config['items_path']), exist_ok=True)
    open(config['items_path'],'w', encoding='utf8').write(items)
    # export sitemap:
    sitemap_template = open('sitemap.template','r', encoding='utf8').read()
    sitemap = sitemap_template.replace('###sitemap###', sitemap)
    #sitemap = sitemap.replace('###selections###', selections)
    os.makedirs(os.path.dirname(config['sitemaps_path']), exist_ok=True)
    open(config['sitemaps_path'],'w', encoding='utf8').write(sitemap)

    #export persistent
    private_persistence = ''
    if os.path.isfile("private_persistence"):
        private_persistence = open('private_persistence','r', encoding='utf8').read()
    persist = '''Strategies {
    everyMinute : "0 * * * * ?"
    everyHour : "0 0 * * * ?"
    everyDay : "0 0 0 * * ?"
    every2Minutes : "0 */2 * ? * *"
    }
    
    Items {
    '''
    for i in export_to_influx:
        persist += f"{i}: strategy = everyUpdate\n"
    persist += private_persistence + '\n}'

    os.makedirs(os.path.dirname(config['influx_path']), exist_ok=True)
    open(config['influx_path'],'w', encoding='utf8').write(persist)


    fenster_rule = ''
    for i in fensterkontakte:
        fenster_rule += f'var save_fk_count_{i["item_name"]} = 0 \n'
    fenster_rule += '''
    rule "fensterkontakt check"
    when
        Time cron "0 * * * * ? *"
    then
    '''
    for i in fensterkontakte:
        fenster_rule += f'    if({i["item_name"]}.state == OPEN){{ \n'
        fenster_rule += f'         save_fk_count_{i["item_name"]} += 1\n'
        fenster_rule += f'         if(save_fk_count_{i["item_name"]} == 15) {{\n'
        fenster_rule +=  '             val telegramAction = getActions("telegram","telegram:telegramBot:Telegram_Bot"); \n'
        fenster_rule += f'             telegramAction.sendTelegram("{i["name"]} seit über 15 Minuten offen!");\n'
        fenster_rule +=  '         }\n'
        fenster_rule +=  '    } else { \n'
        fenster_rule += f'        save_fk_count_{i["item_name"]} = 0; \n'
        fenster_rule +=  '    } \n'
    fenster_rule += '''
    end
    '''
    os.makedirs(os.path.dirname(config['fenster_path']), exist_ok=True)
    open(config['fenster_path'],'w', encoding='utf8').write(fenster_rule)

def main():
    """Main function"""
    logging.basicConfig()
    #read_csvexport()
    gen_building()
    check_unused_addresses()
    export_output()

if __name__ == "__main__":
    main()

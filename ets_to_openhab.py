"""Module providing a collection of function to generate openhab things/items/sitemap from a knxproject"""
import re
import os
import logging
import shutil
from config import config, datapoint_mappings,normalize_string
from utils import get_datapoint_type
from ets_helpers import get_co_flags, flags_match, get_dpt_from_dco

logger = logging.getLogger(__name__)

pattern_items_Name: str = config['regexpattern']['items_Name']
pattern_items_Label: str = config['regexpattern']['items_Label']

#global house,all_addresses,used_addresses
GWIP=None
B_HOMEKIT=False
B_ALEXA=False
HOMEKIT_MAX_ACCESSORIES_PER_INSTANCE=130
floors = []
all_addresses = []
export_to_influx = []
used_addresses = []
equipments={}
FENSTERKONTAKTE = []
PRJ_NAME = 'Our Home'

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
    
    def get_address_from_dco_enhanced(co, config_key, define):
        """
        Enhanced search for group addresses with flag and DPT filtering.
        
        Args:
            co: Base communication object
            config_key: Key in the define config (e.g. 'status_suffix')
            define: Definition from config.json (e.g. config['defines']['dimmer'])
        
        Returns:
            dict or None: Found group address or None
        
        Example:
            dimmwert_status = get_address_from_dco_enhanced(
                co,
                'status_suffix',
                config['defines']['dimmer']
            )
        """
        # Extract configuration
        function_texts_key = config_key
        dpts_key = config_key.replace('_suffix', '_dpts')
        flags_key = config_key.replace('_suffix', '_flags')
        
        # Get config values (with fallback to old method)
        function_texts = define.get(function_texts_key, [])
        expected_dpts = define.get(dpts_key, None)
        expected_flags = define.get(flags_key, None)
        
        # Channel/Text grouping
        group_channel = co.get("channel")
        group_text = co.get("text")
        
        if "device_communication_objects" not in co:
            return None
        
        # Collect candidates
        candidates = []
        
        # Sort candidates by number (ascending) to behave deterministically
        sorted_dcos = sorted(co["device_communication_objects"], key=lambda x: int(x.get("number", 999999)))
        
        for dco in sorted_dcos:
            # Filter 1: Channel/Text match
            if group_channel:
                if group_channel != dco.get("channel"):
                    continue
            elif group_text:
                if group_text != dco.get("text"):
                    continue
            
            # Filter 2: DPT filtering (if defined in config)
            if expected_dpts:
                dco_dpst = get_dpt_from_dco(dco)
                if dco_dpst:
                    if dco_dpst not in expected_dpts:
                        continue
                else:
                    continue
            
            # Filter 3: Flag filtering (if defined in config)
            if expected_flags:
                dco_flags = get_co_flags(dco)
                if not flags_match(dco_flags, expected_flags):
                    continue
            
            # Filter 4: Function text (only as fallback if neither DPT nor flags are defined)
            # If DPT or flags are defined, we rely on those instead of function_text
            if not expected_dpts and not expected_flags:
                # No DPT/flag filtering - use function_text as primary filter
                if function_texts:
                    if normalize_string(dco.get("function_text", "")) not in function_texts:
                        continue
            
            # Search for group address
            search_address = [x for x in all_addresses 
                             if x["Address"] in dco.get('group_address_links', [])]
            
            if search_address:
                candidates.append({
                    'dco': dco,
                    'addresses': search_address,
                    'channel_match': group_channel == dco.get("channel") if group_channel else False
                })
        
        if not candidates:
            return None
        
        # Prioritization:
        # 1. Channel match
        # 2. Fewest linked addresses
        candidates.sort(key=lambda x: (
            not x['channel_match'],
            len(x['addresses'])
        ))
        
        best_candidate = candidates[0]
        if len(best_candidate['addresses']) == 1:
            return best_candidate['addresses'][0]
        else:
            return min(best_candidate['addresses'],
                      key=lambda sa: len(sa.get("communication_object", [])))
    
    def get_address_from_dco(co,config_functiontexts):
        """
        Diese Funktion sucht in einem Kommunikationsobjekt (co) nach einem Funktions-Text und filtert nach Gruppenzugehörigkeit entweder über die Channels oder über den 'text'.

        Args:
            co (dict): Ein einzelnes Kommunikationsobjekt.
            config_functiontexts (list): Eine Liste von Funktions-Texten, die gesucht werden sollen.

        Returns:
            dict or None: Das gefundene Kommunikationsobjekt oder None, wenn keines gefunden wurde.
        """
        group_channel = None
        group_text = None
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
    
    def process_description(descriptions, variable):
        """
        Process description parts and update corresponding variables.
        """
        for description in descriptions:
            if description == 'debug':
                variable['visibility'] = 'visibility=[extended_view==ON]'
            elif description.startswith('icon='):
                variable['icon'] = '<' + description.replace('icon=', '') + '>'
            elif description.startswith('semantic='):
                variable['semantic'] = '["' + description.replace('semantic=', '').replace(',', '","') + '"] '
            elif description.startswith('synonyms='):
                variable['synonyms'] = '{ ' + description.replace('synonyms=', 'synonyms="').replace(',', ', ') + '" } '
            elif description.startswith('name='):
                variable['name'] = description.replace('name=', '')
        return variable
    
    def generate_floor_configuration(floor, floor_nr):
        """
        Generate configuration entries for a floor.
        """
        floor_configuration = ''
        floor_name = floor['Group name']
        if config['general']['FloorNameFromDescription'] and floor['Description'] != '':
            floor_name = floor['Description']
        description = floor['Description'].split(';')
        floor_variables = {'visibility': '', 'semantic': '["Location"]', 'synonyms': '', 'icon': '','name':floor_name}
        floor_variables = process_description(description, floor_variables)

        floor_configuration += f"Group   map{floor_nr}   \"{floor_variables['name']}\" {floor_variables['icon']} (Base) {floor_variables['semantic']} {floor_variables['synonyms']}\n"
        floor_configuration += f"Group:Rollershutter:AVG        map{floor_nr}_Blinds         \"{floor_variables['name']} Jalousie/Rollo\"                      <rollershutter>    (map{floor_nr})                  [\"Blinds\"]         {{stateDescription=\"\"[pattern=\"%.1f %unit%\"]}} \n"
        floor_configuration += f"Group:Switch:OR(ON, OFF)       map{floor_nr}_Lights         \"{floor_variables['name']} Beleuchtung\"                         <light>            (map{floor_nr})                  [\"Light\"] \n"
        #floor_configuration += f"Group:Switch:OR(ON, OFF)       map{floor_nr}_Presence       \"{floor_variables['name']} Präsenz [MAP(presence.map):%s]\"      <presence>         (map{floor_nr},Base)                  [\"Presence\"] \n"
        floor_configuration += f"Group:Contact:OR(OPEN, CLOSED) map{floor_nr}_Contacts       \"{floor_variables['name']} Öffnungsmelder\"                      <contact>          (map{floor_nr})                [\"OpenState\"] \n"
        floor_configuration += f"Group:Number:Temperature:AVG   map{floor_nr}_Temperature    \"{floor_variables['name']} Ø Temperatur\"                        <temperature>      (map{floor_nr})             [\"Measurement\", \"Temperature\"]        {{stateDescription=\"\"[pattern=\"%.1f %unit%\"]}} \n"
        return floor_configuration, floor_name
    
    def generate_room_configuration(room, floor_nr, room_nr):
        """
        Generate configuration entries for a room.
        """
        room_configuration = ''
        room_name = room['Group name']
        if config['general']['RoomNameFromDescription'] and room['Description'] != '':
            room_name = room['Description']
        #room_name_original = room_name
        description = room['Description'].split(';')
        room_variables = {'visibility': '', 'semantic': f'[\"Room\", \"{room_name}\"]', 'icon': '', 'synonyms': '', 'name': room_name}
        room_variables = process_description(description, room_variables)

        room_configuration += f"Group   map{floor_nr}_{room_nr}   \"{room_variables['name']}\"  {room_variables['icon']}  (map{floor_nr})   {room_variables['semantic']} {room_variables['synonyms']}\n"
        return room_configuration, room_name, room_variables
    
    items=''
    sitemap=''
    things=''
    floor_nr=0
    homekit_instance = 1
    homekit_accessorie = 0
    for floor in floors:
        floor_nr += 1
        floor_configuration, floor_name = generate_floor_configuration(floor, floor_nr)
        items += floor_configuration
        sitemap += f"Frame label=\"{floor_name}\" {{\n"

        room_nr = 0
        for room in floor['rooms']:
            room_nr += 1
            room_configuration, room_name, room_variables = generate_room_configuration(room, floor_nr, room_nr)
            items += room_configuration
            sitemap += f"     Group item=map{floor_nr}_{room_nr} {room_variables['visibility']} label=\"{room_name}\" "
            group = ""

            addresses = room['Addresses']
            logger.debug("Room: %s and %s Adresses",room_name,len(addresses))
            # the loop has to be executed twice.
            # - during the first run, all GAs are processed which can have a reference to another GA (e.g. a switch with status feedback)
            #   and also all GAs which can not have a reference to another GA. (e.g. temperatures)
            # - during the second run, all not marked componentes are processed directly with no reference check
            for run in range(3):
                for i in range(len(addresses)):

                    address = room['Addresses'][i]
                    # in the second run: only process not already used addresses
                    #if run > 0:
                    if not any(item['Address'] == address['Address'] for item in all_addresses):
                    #if address['Address'] not in all_addresses:
                        continue
                    if address['Address'] == '3/1/11':
                        logger.debug("Adress found - Breakpoint?")

                    used = False
                    auto_add = False
                    item_icon = None
                    co=None
                    sitemap_type = 'Default'
                    mappings = ''
                    metadata = ''
                    meta_homekit=''
                    meta_alexa=''
                    semantic_info=''
                    #lovely_name = ' '.join(address['Group name'].replace(house[floor_nr]['rooms'][room_nr]['Group name'],'').replace(house[floor_nr]['Group name'],'').split())
                    lovely_name = address['Group name']
                    item_label = lovely_name
                    item_type = ''
                    thing_address_info = ''
                    description = address['Description'].casefold().split(';')
                    equipment = ''
                    equip_homekit = ''
                    equip_alexa = ''
                    grp_metadata=''
                    floor_grp=None
                    define=None

                    #print(f"--- processing: {lovely_name}")
                    #print(address)

                    if 'ignore' in description:
                        continue

                    shortened_name = ' '.join(address['Group name'].replace(room['Group name'],'').replace(room['name_short'],'').replace(floor['Group name'],'').replace(floor['name_short'],'').split())
                    item_name = f"i_{floor['name_short']}_{room['name_short']}_{shortened_name}"
                    item_name = item_name.translate(config['special_char_map'])
                    item_name = re.sub(pattern_items_Name, '', item_name)
                    if run == 0:
                        # dimmer
                        if address['DatapointType'] == get_datapoint_type('dimmer'):
                            define=config['defines']['dimmer']
                            #bol = [x for x in define['absolut_suffix'] if x in address['Group name']]
                            co = get_co_by_functiontext(address,define['absolut_suffix'])
                            if not co:
                                continue

                            basename = address['Group name']
                            dimmwert_status=get_address_from_dco_enhanced(co,'status_suffix',define)
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
                                relative_command=get_address_from_dco_enhanced(co,'relativ_suffix',define)
                                if relative_command:
                                    used_addresses.append(relative_command['Address'])
                                    relative_option = f", increaseDecrease=\"{relative_command['Address']}\""
                                switch_command=get_address_from_dco_enhanced(co,'switch_suffix',define)
                                if switch_command:
                                    used_addresses.append(switch_command['Address'])
                                    switch_status_command=get_address_from_dco_enhanced(co,'switch_status_suffix',define)
                                    if switch_status_command:
                                        used_addresses.append(switch_status_command['Address'])
                                        switch_option_status = f"+<{switch_status_command['Address']}"
                                    switch_option = f", switch=\"{switch_command['Address']}{switch_option_status}\""

                                auto_add = True
                                item_type = "Dimmer"
                                thing_address_info = f"position=\"{address['Address']}+<{dimmwert_status['Address']}\"{switch_option}{relative_option}"
                                equipment = 'Lightbulb'
                                semantic_info = "[\"Light\"]"
                                item_icon = "light"
                                if B_HOMEKIT:
                                    meta_homekit=', homekit="Lighting, Lighting.Brightness"'
                                if B_ALEXA:
                                    meta_alexa=', alexa = "Light"'
                            else:
                                logger.error("incomplete dimmer: %s / %s",basename,address['Address'])

                        # rollos / jalousien
                        elif address['DatapointType'] == get_datapoint_type('rollershutter'):
                            define=config['defines']['rollershutter']
                            co = get_co_by_functiontext(address,define['up_down_suffix'])
                            if not co:
                                continue

                            basename = address['Group name']
                            fahren_auf_ab = address
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
                                fahren_stop=get_address_from_dco_enhanced(co,'stop_suffix',define)
                                if fahren_stop:
                                    used_addresses.append(fahren_stop['Address'])
                                    option_stop = f", stopMove=\"{fahren_stop['Address']}\""
                                absolute_position=get_address_from_dco_enhanced(co,'absolute_position_suffix',define)
                                absolute_position_status=get_address_from_dco_enhanced(co,'status_suffix',define)
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
                                equipment = 'Blinds'
                                semantic_info = "[\"Blinds\"]"
                                item_icon = "rollershutter"
                                if B_HOMEKIT:
                                    equip_homekit='homekit = "WindowCovering"'
                                    meta_homekit=', homekit = "CurrentPosition, TargetPosition, PositionState"'
                                if B_ALEXA:
                                    equip_alexa='alexa = "Blind"'
                                    meta_alexa=', alexa = "PositionState"'
                            else:
                                logger.error("incomplete rollershutter: %s",basename)

                        # Heizung
                        elif address['DatapointType'] in (get_datapoint_type('heating'), get_datapoint_type('heating_mode')):
                            define=config['defines']['heating']
                            co = get_co_by_functiontext(address,define['level_suffix'])
                            if  not co:
                                continue
                            basename = address['Group name']
                            betriebsmodus = address
                            option_status_betriebsmodus=''
                            if betriebsmodus:
                                used_addresses.append(betriebsmodus['Address'])
                                betriebsmodus_status=get_address_from_dco_enhanced(co,'status_level_suffix',define)
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
                                if B_HOMEKIT:
                                    equip_homekit='homekit = "Thermostat"'
                                    meta_homekit=', homekit = \"CurrentHeatingCoolingMode, TargetHeatingCoolingMode\" [OFF=\"4\", HEAT=\"1\", COOL=\"2\"]'
                                if B_ALEXA:
                                    equip_alexa='alexa = "Thermostat"'
                                    meta_alexa=', alexa = \"HeatingCoolingMode\" [OFF=\"4\", HEAT=\"1\", COOL=\"2\"]'
                                semantic_info = "[\"HVAC\"]"
                                item_icon = "heating_mode"
                                metadata=', stateDescription=\"\"[options=\"NULL=unbekannt ...,1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"], commandDescription=\"\"[options=\"1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"], listWidget=\"\"[iconUseState=\"true\"]'

                            else:
                                logger.error("incomplete heating: %s",basename)

                    #  erst im zweiten durchlauf prüfen damit integrierte Schaltobjekte (z.B. dimmen) vorher schon erkannt werden.
                    if run > 0:
                        # Schalten or bool
                        if address['DatapointType'] == get_datapoint_type('switch'):
                            define=config['defines']['switch']
                            item_type = "Switch"
                            item_label = lovely_name
                            co = get_co_by_functiontext(address,define['switch_suffix'])
                            if  not co:
                                continue

                            basename = address['Group name']
                            status=get_address_from_dco_enhanced(co,'status_suffix',define)
                            if status:
                                auto_add = True
                                used_addresses.append(status['Address'])
                                thing_address_info = f"ga=\"{address['Address']}+<{status['Address']}\""
                            else:
                                auto_add = True
                                thing_address_info = f"ga=\"{address['Address']}\""
                            semantic_info = "[\"Switch\"]"
                            item_icon = "switch"
                            if B_HOMEKIT:
                                meta_homekit=', homekit="Switchable"'
                            if B_ALEXA:
                                meta_alexa=', alexa = "Switch"'


                    ######## determined only by datapoint
                    # do this only after items with multiple addresses are processed:
                    # e.g. the state datapoint could be an own thing or the feedback from a switch or so
                    if run > 1:
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
                                if B_HOMEKIT:
                                    meta_homekit=f"{mapping_info['homekit']}"
                                if B_ALEXA:
                                    meta_alexa=f"{mapping_info['alexa']}"
                                semantic_info = f"{mapping_info['semantic_info']}"
                                item_icon = mapping_info['item_icon']
                                if 'Soll' in lovely_name:
                                    semantic_info = semantic_info.replace("Measurement","Setpoint")
                                    meta_homekit = meta_homekit.replace("CurrentTemperature","TargetTemperature")
                                break
                        # window/door
                        if address['DatapointType'] == get_datapoint_type('window_contact'):
                            equipment = 'Window'
                            FENSTERKONTAKTE.append({'item_name': item_name, 'name': address['Group name']})

                        # Szene
                        if address['DatapointType'] == get_datapoint_type('scene'):
                            used = True
                            ga = "17.001"
                            if address['DatapointType'] == 'DPST-18-1':
                                ga="18.001"

                            for idescription in description:
                                if '=' in idescription:
                                    mappings = idescription
                                    break

                            if mappings!= '':
                                data_map = mappings.replace("'","").split(",")
                                for index,word in enumerate(data_map):
                                    number_part, word_part = word.strip().split('=')
                                    data_map[index] = f"{(int(number_part) - 1)}.0={word_part}"

                                data_str = ','.join(data_map)
                                metadata=f', stateDescription=\"\"[options=\"NULL=unbekannt ...,{data_str}\"], commandDescription=\"\"[options=\"{data_str}\"]'
                                item_label = lovely_name

                                auto_add = True
                                item_type = "Number"
                                thing_address_info = f"ga=\"{ga}:{address['Address']}\""
                                semantic_info = "[\"Equipment\"]"
                                item_icon = "movecontrol"
                                sitemap_type = "Selection"
                            else:
                                logger.info("no mapping for scene %s %s",address['Address'], address['Group name'])

                    if define and 'change_metadata' in define:
                        for item in define['change_metadata']:
                            if item in address['Group name']:
                                for var in define['change_metadata'][item]:
                                    match var:
                                        case 'semantic_info':
                                            semantic_info = define['change_metadata'][item][var]
                                        case 'item_icon':
                                            item_icon = define['change_metadata'][item][var]
                                        case 'equipment':
                                            equipment = define['change_metadata'][item][var]
                                        case 'homekit':
                                            if B_HOMEKIT:
                                                meta_homekit=define['change_metadata'][item][var]
                                        case 'alexa':
                                            if B_ALEXA:
                                                meta_alexa=define['change_metadata'][item][var]

                    if used:
                        used_addresses.append(address['Address'])

                    if auto_add:
                        used_addresses.append(address['Address'])
                        item_variables = {'visibility': '', 'semantic': semantic_info, 'synonyms': '', 'icon': item_icon,'name':item_label}
                        item_variables = process_description(description, item_variables)
                        semantic_info = item_variables['semantic']
                        item_icon = item_variables['icon']
                        synonyms = item_variables['synonyms']
                        item_label = item_variables['name']
                        # remove generic description if unneccessary
                        item_label_short = item_label
                        for drop in config['defines']['drop_words']:
                            item_label_short = item_label_short.replace(drop,'')
                        # remvoe floor and room from label
                        if floor['name_short']:
                            item_label_short=item_label_short.replace(floor['name_short'],'')
                        # remove text by item_label pattern
                        item_label_short = re.sub(pattern_items_Label, '', item_label_short)
                        item_label_short=item_label_short.replace('|',' ')
                        item_label_short=item_label_short.replace('  ',' ')
                        if item_label_short != '':
                            item_label = item_label_short

                        if not item_icon:
                            item_icon = ""
                        elif not item_icon.startswith('<'):
                            item_icon = f"<{item_icon}>"

                        item_label = item_label.replace(room['Group name'], room_name)
                        item_label = re.sub(r'\[.*\]', '', item_label)
                        item_label = re.sub(r'\|.*\:', '', item_label)
                        item_label = re.sub(r'^\W+|\W+$', '', item_label) # removes special cahrs on start/end
                        item_label = item_label.strip()

                        thing_type = item_type.lower().split(":")[0]
                        things += f"Type {thing_type}    :   {item_name}   \"{address['Group name']}\"   [ {thing_address_info} ]\n"

                        root = f"map{floor_nr}_{room_nr}"
                        if equipment != '':
                            if not item_label in equipments:
                                equipments[item_label]=item_name
                                if equip_homekit:
                                    equip_homekit+=f" [Instance={homekit_instance}]"
                                    grp_metadata += equip_homekit
                                if equip_alexa:
                                    if grp_metadata:
                                        grp_metadata+=", "
                                    grp_metadata+= equip_alexa
                                if grp_metadata:
                                    grp_metadata=f"{{ {grp_metadata} }}"
                                items += f"Group   equipment_{item_name}   \"{item_label}\"  {item_icon}  ({root})   [\"{equipment}\"] {grp_metadata}\n"
                                root = f"equipment_{item_name}"
                            else:
                                root = f"equipment_{equipments[item_label]}"
                        if item_label in equipments:
                            root = f"equipment_{equipments[item_label]}"
                        if B_HOMEKIT and meta_homekit:
                            if ']' in meta_homekit:
                                meta_homekit= meta_homekit.replace(']',f" ,Instance={homekit_instance}]")
                            else:
                                meta_homekit+=f" [Instance={homekit_instance}]"
                            metadata+=meta_homekit
                            homekit_accessorie+=1
                        if B_ALEXA and meta_alexa:
                            metadata+=meta_alexa
                        if floor_grp:
                            root= f"{root},{floor_grp}"

                        items += f"{item_type}   {item_name}   \"{item_label}\"   {item_icon}   ({root})   {semantic_info}    {{ channel=\"knx:device:bridge:generic:{item_name}\" {metadata}{synonyms} }}\n"
                        group += f"        {sitemap_type} item={item_name} label=\"{item_label}\" {item_variables['visibility']}\n"

                        if homekit_accessorie >= HOMEKIT_MAX_ACCESSORIES_PER_INSTANCE:
                            homekit_accessorie=0
                            homekit_instance+=1
                        if 'influx' in address['Description']:
                            export_to_influx.append(item_name)
                    while used_addresses:
                        a = used_addresses.pop()
                        found_item = next((item for item in all_addresses if item['Address'] == a), None)
                        if found_item:
                            all_addresses.remove(found_item)

            if group != '':
                sitemap += f" {{\n{group}\n    }}\n"
            else:
                sitemap += "\n"
        sitemap += "}\n"
    return items,sitemap,things

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

def check_unused_addresses():
    """Logs all unused addresses for further manual actions"""
    # process all addresses which were not used
    for address in all_addresses:
        logger.debug("unused: %s: %s with type %s",address['Address'],address['Group name'],address['DatapointType'])

def set_permissions(file_path, configuration=None):
    """
    Sets ownership of the file to the configured user:group.
    """
    cfg = configuration if configuration is not None else config
    
    target_user = cfg.get('target_user')
    target_group = cfg.get('target_group')
    
    if not target_user and not target_group:
        return

    try:
        shutil.chown(file_path, user=target_user, group=target_group)
        logger.info("Set permissions for %s to %s:%s", file_path, target_user, target_group)
    except Exception as e:
        logger.warning("Failed to set permissions for %s: %s", file_path, e)

def export_output(items,sitemap,things, configuration=None):
    """Exports things / items / sitemap / ...  Files"""
    # Use provided configuration or fallback to global config
    cfg = configuration if configuration is not None else config

    # export things:
    try:
        things_template = open('things.template','r', encoding='utf8').read()
        if GWIP:
            things_template = things_template.replace('###gwip###', GWIP)
        else:
            logger.info("No Gateway IP found. Using KNX Router mode (multicast).")
            things_template = things_template.replace('type="TUNNEL"', 'type="ROUTER"')
            things_template = re.sub(r'.*ipAddress="###gwip###",.*\n', '', things_template)
            things_template = re.sub(r'.*portNumber=3671,.*\n', '', things_template)
            things_template = things_template.replace('autoReconnectPeriod=30', 'autoReconnectPeriod=60')

        things = things_template.replace('###things###', things)
        os.makedirs(os.path.dirname(cfg['things_path']), exist_ok=True)
        with open(cfg['things_path'],'w', encoding='utf8') as f:
            f.write(things)
        logger.info(f"Successfully wrote things file to {cfg['things_path']} with {things.count(chr(10)) + 1} lines")
    except Exception as e:
        logger.error(f"Failed to write things file to {cfg['things_path']}: {e}")
        raise
    # export items:
    try:
        items_template =  open('items.template','r', encoding='utf8').read()
        items = items_template.replace('###items###', items)
        items = items.replace('###NAME###', PRJ_NAME)
        os.makedirs(os.path.dirname(cfg['items_path']), exist_ok=True)
        with open(cfg['items_path'],'w', encoding='utf8') as f:
            f.write(items)
        logger.info(f"Successfully wrote items file to {cfg['items_path']} with {items.count(chr(10)) + 1} lines")
    except Exception as e:
        logger.error(f"Failed to write items file to {cfg['items_path']}: {e}")
        raise
    # export sitemap:
    try:
        sitemap_template = open('sitemap.template','r', encoding='utf8').read()
        sitemap = sitemap_template.replace('###sitemap###', sitemap)
        os.makedirs(os.path.dirname(cfg['sitemaps_path']), exist_ok=True)
        with open(cfg['sitemaps_path'],'w', encoding='utf8') as f:
            f.write(sitemap)
        logger.info(f"Successfully wrote sitemap file to {cfg['sitemaps_path']} with {sitemap.count(chr(10)) + 1} lines")
    except Exception as e:
        logger.error(f"Failed to write sitemap file to {cfg['sitemaps_path']}: {e}")
        raise

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

    try:
        os.makedirs(os.path.dirname(cfg['influx_path']), exist_ok=True)
        with open(cfg['influx_path'],'w', encoding='utf8') as f:
            f.write(persist)
        logger.info(f"Successfully wrote persistence file to {cfg['influx_path']} with {persist.count(chr(10)) + 1} lines")
    except Exception as e:
        logger.error(f"Failed to write persistence file to {cfg['influx_path']}: {e}")
        raise


    fenster_rule = ''
    for i in FENSTERKONTAKTE:
        fenster_rule += f'var save_fk_count_{i["item_name"]} = 0 \n'
    fenster_rule += '''\n    rule "fensterkontakt check"
    when
        Time cron "0 * * * * ? *"
    then
    '''
    for i in FENSTERKONTAKTE:
        fenster_rule += f'    if({i["item_name"]}.state == OPEN){{ \n'
        fenster_rule += f'         save_fk_count_{i["item_name"]} += 1\n'
        fenster_rule += f'         if(save_fk_count_{i["item_name"]} == 15) {{\n'
        fenster_rule +=  '             val telegramAction = getActions("telegram","telegram:telegramBot:Telegram_Bot"); \n'
        fenster_rule += f'             telegramAction.sendTelegram("{i["name"]} seit über 15 Minuten offen!");\n'
        fenster_rule +=  '         }\n'
        fenster_rule +=  '    } else { \n'
        fenster_rule += f'        save_fk_count_{i["item_name"]} = 0; \n'
        fenster_rule +=  '    } \n'
    fenster_rule += '''\n    end
    '''
    try:
        os.makedirs(os.path.dirname(cfg['fenster_path']), exist_ok=True)
        with open(cfg['fenster_path'],'w', encoding='utf8') as f:
            f.write(fenster_rule)
        logger.info(f"Successfully wrote window rule file to {cfg['fenster_path']} with {fenster_rule.count(chr(10)) + 1} lines")
    except Exception as e:
        logger.error(f"Failed to write window rule file to {cfg['fenster_path']}: {e}")
        # This is not critical, so we don't raise an exception

def main(configuration=None):
    """Main function"""
    logging.basicConfig()
    items,sitemap,things=gen_building()
    check_unused_addresses()
    export_output(items,sitemap,things, configuration=configuration)

if __name__ == "__main__":
    main()

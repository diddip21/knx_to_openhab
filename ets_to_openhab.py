import csv
import os
import json
import re

with open('config.json', encoding='utf8') as f:
    config = json.load(f)

def data_of_name(data, name, suffix,replace=''):
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

special_char_map = {
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

global house,all_addresses,used_addresses
house = []
all_addresses = []
export_to_influx = []
used_addresses = []
items = ''
sitemap = ''
things = ''
semantic_things = ''
selections = ''
semantic_cnt = 0
fensterkontakte = []
cnt = 0

def read_csvexport():
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
                print("ignoreflag in description for: " + row['Group name'])
                continue
            house[int(splitter[0])]['rooms'][int(splitter[1])]['Addresses'].append(row)
            all_addresses.append(row)

def genBuilding():
    def getCoByFunctionText(cos,config_functiontexts):
        if "communication_object" in cos:
            for co in cos["communication_object"]:
                 if co["function_text"] in config_functiontexts:
                     return co
        return None        
    def getFromMultiCo(cos,config_functiontexts):
        if "communication_object" in cos:
            for co in cos["communication_object"]:
                itemco=getFromDco(co,config_functiontexts)
                if itemco is not None:
                    return itemco
        return None
    def getFromDco(co,config_functiontexts):
        if "device_communication_objects" in co:
            for y in co["device_communication_objects"]:
                if y["function_text"] in config_functiontexts:
                    search_address = [x for x in all_addresses if (x["Address"] in y['group_address_links'])]
                    if len(search_address)==1:
                        return search_address[0]
                    elif len(search_address) > 1:
                        lowLenCo = 99
                        lowCo=None
                        for sa in search_address:
                            if "communication_object" in sa:
                                if len(sa["communication_object"]) < lowLenCo:
                                    lowLenCo=len(sa["communication_object"])
                                    lowCo = sa
                        return lowCo
        return None
    global items,sitemap,things
    floorNr=0
    for floor in house:
        floorNr+=1
        floorName = floor['Group name']
        if config['general']['FloorNameFromDescription'] and floor['Description'] != '':
            floorName = floor['Description']
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

        items += f"Group   map{floorNr}   \"{floorName}\" {icon}  {semantic} {synonyms} \n" # {location}  \n" # {visibility}
        sitemap += f"Frame label=\"{floorName}\" {{\n"
        roomNr=0
        for room in floor['rooms']:
            roomNr+=1
            roomName = room['Group name']
            if config['general']['RoomNameFromDescription'] and room['Description'] != '':
                roomName = room['Description']
            roomNameOrig = roomName
            descriptions = room['Description'].split(';')
            visibility = ''
            semantic = f"[\"Location\", \"Room\", \"{roomName}\"]"
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
                    roomName = description.replace('name=','')

            items += f"Group   map{floorNr}_{roomNr}   \"{roomName}\"  {icon}  (map{floorNr})   {semantic} {synonyms}\n"
            sitemap += f"     Group item=map{floorNr}_{roomNr} {visibility} label=\"{roomName}\" "
            group = ""

            addresses = room['Addresses']

            # the loop has to be executed twice.
            # - during the first run, all GAs are processed which can have a reference to another GA (e.g. a switch with status feedback)
            #   and also all GAs which can not have a reference to another GA. (e.g. temperatures)
            # - during the second run, all not marked componentes are processed directly with no reference check
            for run in range(2):
                for i in range(len(addresses)):

                    address = room['Addresses'][i]
                    # in the second run: only process not already used addresses
                    #if run > 0:
                    if address['Address'] in used_addresses:
                        continue
                    if address['Address'] == '3/0/14':
                        print("Adress found - Breakpoint?")

                    used = False
                    auto_add = False
                    item_icon = None
                    co=None
                    sitemap_type = 'Default'
                    mappings = ''
                    metadata = ''
                    #lovely_name = ' '.join(address['Group name'].replace(house[floorNr]['rooms'][roomNr]['Group name'],'').replace(house[floorNr]['Group name'],'').split())
                    lovely_name = address['Group name']
                    item_label = lovely_name
                    descriptions = address['Description'].split(';')
                    equipment = ''

                    #print(f"--- processing: {lovely_name}")
                    #print(address)

                    if 'IGNORE' in address.keys():
                        continue

                    shortened_name = ' '.join(address['Group name'].replace(room['Group name'],'').replace(floor['Group name'],'').split())
                    item_name = f"i_{cnt}_{floor['Group name']}_{room['Group name']}_{shortened_name}"
                    item_name = item_name.translate(special_char_map)
                    item_name = re.sub('[^A-Za-z0-9_]+', '', item_name)
                    
                    if run == 0:
                        # dimmer
                        if address['DatapointType'] == 'DPST-5-1':
                            bol = [x for x in config['defines']['dimmer']['absolut_suffix'] if(x in address['Group name'])]
                            co = getCoByFunctionText(address,config['defines']['dimmer']['absolut_suffix'])
                            if not bool(bol) and not co:
                                continue

                            basename = address['Group name']#.replace(config['defines']['dimmer']['absolut_suffix'],'')
                            dimmwert_status =data_of_name(all_addresses, basename, config['defines']['dimmer']['status_suffix'],config['defines']['dimmer']['absolut_suffix'])
                            if not dimmwert_status and co:
                                dimmwert_status=getFromDco(co,config['defines']['dimmer']['status_suffix'])
                            for drop_name in config['defines']['dimmer']['drop']:
                                drop_addr = data_of_name(all_addresses, basename, drop_name,config['defines']['dimmer']['absolut_suffix'])
                                if drop_addr:
                                    used_addresses.append(drop_addr['Address'])
                            
                            switch_option = ''; switch_option_status = ''
                            if dimmwert_status:
                                used = True 
                                used_addresses.append(dimmwert_status['Address'])
                                relative_command = data_of_name(all_addresses, basename, config['defines']['dimmer']['relativ_suffix'],config['defines']['dimmer']['absolut_suffix'])
                                if not relative_command and co:
                                    relative_command=getFromDco(co,config['defines']['dimmer']['relativ_suffix'])  
                                switch_command = data_of_name(all_addresses, basename, config['defines']['dimmer']['switch_suffix'],config['defines']['dimmer']['absolut_suffix'])
                                if not switch_command and co:
                                    switch_command=getFromDco(co,config['defines']['dimmer']['switch_suffix'])  
                                if relative_command: 
                                    used_addresses.append(relative_command['Address'])
                                    relative_option = f", increaseDecrease=\"{relative_command['Address']}\""
                                if switch_command:
                                    used_addresses.append(switch_command['Address'])
                                    switch_status_command = data_of_name(all_addresses, basename, config['defines']['dimmer']['switch_status_suffix'],config['defines']['dimmer']['absolut_suffix'])
                                    if not switch_status_command and co:
                                         switch_status_command=getFromDco(co,config['defines']['dimmer']['switch_status_suffix'])  
                                    if switch_status_command:
                                        used_addresses.append(switch_status_command['Address'])
                                        switch_option_status = f"+<{switch_status_command['Address']}"
                                    switch_option = f", switch=\"{switch_command['Address']}{switch_option_status}\""
            
                                lovely_name = ' '.join(lovely_name.replace('Dimmen','').replace('Dimmer','').replace('absolut','').replace('Licht','').split())

                                auto_add = True
                                item_type = "Dimmer"
                                thing_address_info = f"position=\"{address['Address']}+<{dimmwert_status['Address']}\"{switch_option}{relative_option}"
                                item_label = f"{lovely_name} [%d %%]"
                                equipment = 'Lightbulb'
                                semantic_info = "[\"Light\"]"
                                item_icon = "light"
                            else:
                                print(f"incomplete dimmer: {basename} / {address['Address']}")

                        # rollos / jalousien
                        elif address['DatapointType'] == 'DPST-1-8':
                            bol = [x for x in config['defines']['rollershutter']['up_down_suffix'] if(x in address['Group name'])]
                            co = getCoByFunctionText(address,config['defines']['rollershutter']['up_down_suffix'])
                            if not bool(bol) and not co:
                                continue
                            
                            basename = address['Group name'] #.replace(config['defines']['rollershutter']['up_down_suffix'],'')
                            fahren_auf_ab = address
                            #Status Richtung nicht in verwendung durch openhab
                            for drop_name in config['defines']['rollershutter']['drop']:
                                drop_addr = data_of_name(all_addresses, basename, drop_name,config['defines']['rollershutter']['up_down_suffix'])
                                if drop_addr:
                                    used_addresses.append(drop_addr['Address'])
                            
                            option_stop =''; option_position=''; option_position_absolute=''; option_position_status=''
                            if fahren_auf_ab:
                                used_addresses.append(fahren_auf_ab['Address'])
                                fahren_stop = data_of_name(all_addresses, basename, config['defines']['rollershutter']['stop_suffix'],config['defines']['rollershutter']['up_down_suffix'])
                                if not fahren_stop and co:
                                    fahren_stop=getFromDco(co,config['defines']['rollershutter']['stop_suffix']) 
                                if fahren_stop:
                                    used_addresses.append(fahren_stop['Address'])
                                    option_stop = f", stopMove=\"{fahren_stop['Address']}\""
                                absolute_position = data_of_name(all_addresses, basename, config['defines']['rollershutter']['absolute_position_suffix'],config['defines']['rollershutter']['up_down_suffix'])
                                absolute_position_status = data_of_name(all_addresses, basename, config['defines']['rollershutter']['status_suffix'],config['defines']['rollershutter']['up_down_suffix'])
                                if not absolute_position and co:
                                    absolute_position=getFromDco(co,config['defines']['rollershutter']['absolute_position_suffix']) 
                                if not absolute_position_status and co:
                                    absolute_position_status=getFromDco(co,config['defines']['rollershutter']['status_suffix']) 
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
                                item_label = f"{lovely_name} [%d %%]"
                                semantic_info = "[\"Blinds\"]"
                                item_icon = "rollershutter"
                            else:
                                print(f"incomplete rollershutter: {basename}")

                        # Heizung
                        elif address['DatapointType'] in ('DPST-5-010','DPST-20-102'):
                            if address['Address'] in used_addresses:
                                continue
                            bol = [x for x in config['defines']['heating']['level_suffix'] if(x in address['Group name'])]
                            co = getCoByFunctionText(address,config['defines']['heating']['level_suffix'])
                            if not bool(bol) and not co:
                                continue
                            basename = address['Group name'] #.replace(config['defines']['rollershutter']['up_down_suffix'],'')
                            betriebsmodus = address
                            option_status_betriebsmodus=''
                            if betriebsmodus:
                                used_addresses.append(betriebsmodus['Address'])
                                betriebsmodus_status = data_of_name(all_addresses, basename, config['defines']['heating']['status_level_suffix'],config['defines']['heating']['level_suffix'])
                                if not betriebsmodus_status and co:
                                    betriebsmodus_status=getFromDco(co,config['defines']['heating']['status_level_suffix'])
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
                                semantic_info = "[\"HVAC\"]"
                                item_icon = "heating_mode"
                                metadata=", stateDescription=\"\"[options=\"NULL=unbekannt ...,1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"],commandDescription=\"\"[options=\"1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"]"                        

                            else:
                                print(f"incomplete heating: {basename}")

                    #  erst im zweiten durchlauf prüfen damit integrierte Schaltobjekte (z.B. dimmen) vorher schon erkannt werden.
                    if run > 0:
                        # Schalten or bool
                        if address['DatapointType'] == 'DPST-1-1' or address['DatapointType'] == 'DPST-1-2':
                            item_type = "Switch"
                            item_label = lovely_name
                            # umschalten (Licht, Steckdosen)
                            # only add in first round, if there is a status GA for feedback
                            bol = [x for x in config['defines']['switch']['switch_suffix'] if(x in address['Group name'])]
                            co = getCoByFunctionText(address,config['defines']['switch']['switch_suffix'])
                            if not bool(bol) and not co:
                                continue

                            basename = address['Group name']#.replace(config['defines']['dimmer']['absolut_suffix'],'')
                            status =data_of_name(all_addresses, basename, config['defines']['switch']['status_suffix'],config['defines']['switch']['switch_suffix'])
                            if not status and co:
                                status=getFromDco(co,config['defines']['switch']['status_suffix'])                                  
                                if status:
                                    #if status['DatapointType'] == 'DPST-1-11':
                                        auto_add = True
                                        used_addresses.append(status['Address'])
                                        thing_address_info = f"ga=\"{address['Address']}+{status['Address']}\""

                            # in the second run, we accept everything ;)
                            if run > 0:
                                auto_add = True
                                thing_address_info = f"ga=\"1.001:{address['Address']}\""
                                #item_label = f"{lovely_name} [%d]"
                                semantic_info = "[\"Control\", \"Status\"]"

                            if config['defines']['switch']['light_name'] in address['Group name']:
                                semantic_info = "[\"Control\", \"Light\"]"
                                equipment = 'Lightbulb'
                                item_icon = 'light'
                            elif config['defines']['switch']['poweroutlet_name'] in address['Group name']:
                                semantic_info = "[\"Control\", \"Switch\"]"
                                equipment = 'PowerOutlet'
                                item_icon = 'poweroutlet'
                            elif config['defines']['switch']['speaker_name'] in address['Group name']:
                                semantic_info = "[\"Control\", \"Switch\"]"
                                equipment = 'Speaker'
                                item_icon = 'soundvolume'
                            elif config['defines']['switch']['heating_name'] in address['Group name']:
                                semantic_info = "[\"Heating\", \"Switch\"]"
                                equipment = 'HVAC'
                                item_icon = 'radiator'
                            else:
                                semantic_info = "[\"Control\", \"Switch\"]"
                                item_icon = "switch"


                    ######## determined only by datapoint
                    # do this only after items with multiple addresses are processed:
                    # e.g. the state datapoint could be an own thing or the feedback from a switch or so
                    if run > 0:
                        # temperature
                        if address['DatapointType'] == 'DPST-9-1':
                            auto_add = True
                            item_type = "Number:Temperature"
                            thing_address_info = f"ga=\"9.001:{address['Address']}\""
                            item_label = f"{lovely_name}"
                            metadata=", stateDescription=\"\"[pattern=\"%.1f %unit%\"]"

                            semantic_info = "[\"Measurement\", \"Temperature\"]"
                            if 'Soll' in lovely_name:
                                semantic_info = "[\"Setpoint\", \"Temperature\"]"
                            
                            item_icon = "temperature" 

                        # humidity
                        if address['DatapointType'] == 'DPST-9-7':
                            auto_add = True
                            item_type = "Number:Dimensionless"
                            thing_address_info = f"ga=\"9.001:{address['Address']}\""
                            item_label = f"{lovely_name}"
                            metadata=", unit=\"%\", stateDescription=\"\"[pattern=\"%.1f %%\"]"

                            semantic_info = "[\"Measurement\", \"Humidity\"]"
                            if 'Soll' in lovely_name:
                                semantic_info = "[\"Setpoint\", \"Humidity\"]"
                            
                            item_icon = "humidity" 

                        # window/door
                        if address['DatapointType'] == 'DPST-1-19':
                            auto_add = True
                            item_type = "Contact"
                            thing_address_info = f"ga=\"1.019:{address['Address']}\""
                            equipment = 'Window'
                            semantic_info = "[\"OpenState\", \"Opening\"]"
                            
                            fensterkontakte.append({'item_name': item_name, 'name': address['Group name']})

                        # Arbeit (wh)
                        if address['DatapointType'] == 'DPST-13-10':
                            auto_add = True
                            item_type = "Number:Energy"
                            thing_address_info = f"ga=\"13.010:{address['Address']}\""
                            item_label = f"{lovely_name} [%.1f Wh]"
                            semantic_info = "[\"Measurement\", \"Energy\"]"
                            item_icon = "batterylevel"

                        # Tag/Nacht
                        if address['DatapointType'] == 'DPST-1-24':
                            auto_add = True
                            item_type = "Switch"
                            thing_address_info = f"ga=\"1.024:{address['Address']}\""
                            item_label = f"{lovely_name}"
                            semantic_info = "[\"Control\"]"
                            item_icon = "moon"

                        # Alarm
                        if address['DatapointType'] == 'DPST-1-5':
                            auto_add = True
                            item_type = "Switch"
                            thing_address_info = f"ga=\"1.005:{address['Address']}\""
                            item_label = f"{lovely_name}"
                            semantic_info = "[\"Alarm\"]"
                            item_icon = "alarm"

                        # Leistung (W)
                        if address['DatapointType'] == 'DPST-14-56':
                            auto_add = True
                            item_type = "Number:Power"
                            thing_address_info = f"ga=\"14.056:{address['Address']}\""
                            item_label = f"{lovely_name} [%.1f W]"
                            semantic_info = "[\"Measurement\", \"Power\"]"
                            item_icon = "energy"

                        # Strom
                        if address['DatapointType'] == 'DPST-7-12':
                            auto_add = True
                            item_type = "Number:ElectricCurrent"
                            thing_address_info = f"ga=\"7.012:{address['Address']}\""
                            item_label = f"{lovely_name} [%.1f mA]"
                            semantic_info = "[\"Measurement\", \"Current\"]"
                            item_icon = "energy"

                        # Volumen (l)
                        if address['DatapointType'] == 'DPST-12-1200':
                            auto_add = True
                            item_type = "Number:Volume"
                            thing_address_info = f"ga=\"12.1200:{address['Address']}\""
                            item_label = f"{lovely_name} [%.0f l]"
                            semantic_info = "[\"Measurement\", \"Volume\"]"
                            item_icon = "water"

                        # String
                        if address['DatapointType'] == 'DPST-16-0' or address['DatapointType'] == 'DPT-16':
                            auto_add = True
                            item_type = "String"
                            thing_address_info = f"ga=\"16.000:{address['Address']}\""
                            #item_label = f"{lovely_name}"
                            #semantic_info = ""
                            item_icon = "text"

                        # Lux
                        if address['DatapointType'] == 'DPST-9-4':
                            auto_add = True
                            item_type = "Number:Illuminance"
                            thing_address_info = f"ga=\"9.004:{address['Address']}\""
                            item_label = f"{lovely_name} [%.1f Lux]"
                            semantic_info = "[\"Measurement\", \"Light\"]"
                            item_icon = "sun"

                        # Geschwindigkeit m/s
                        if address['DatapointType'] == 'DPST-9-5':
                            auto_add = True
                            item_type = "Number:Speed"
                            thing_address_info = f"ga=\"9.005:{address['Address']}\""
                            item_label = f"{lovely_name} [%.1f m/s]"
                            semantic_info = "[\"Measurement\", \"Wind\"]"
                            item_icon = "wind"

                        # ppm
                        if address['DatapointType'] == 'DPST-9-8':
                            auto_add = True
                            item_type = "Number:Dimensionless"
                            thing_address_info = f"ga=\"9.008:{address['Address']}\""
                            item_label = f"{lovely_name} [%.1f ppm]"
                            semantic_info = "[\"Measurement\"]"

                        # percent
                        if address['DatapointType'] == 'DPST-5-1':
                            auto_add = True
                            item_type = "Dimmer"
                            thing_address_info = f"ga=\"5.001:{address['Address']}\""
                            item_label = f"{lovely_name} [%d %%]"
                            semantic_info = "[\"Measurement\"]"

                        # Zeitdifferenz 
                        if address['DatapointType'] == 'DPST-13-100':
                            auto_add = True
                            item_type = "Number:Time"
                            thing_address_info = f"ga=\"13.100:{address['Address']}\""
                            item_label = f"{lovely_name} [%.1f s]"
                            semantic_info = "[\"Measurement\", \"Duration\"]"
                            item_icon = "time"

                        # Datum/Uhrzeit 
                        if address['DatapointType'] == 'DPST-19-1':
                            auto_add = True
                            item_type = "DateTime"
                            thing_address_info = f"ga=\"{address['Address']}\""
                            item_label = f"{lovely_name}"
                            semantic_info = ""
                            item_icon = "time"
                        # Szene
                        if address['DatapointType'] in ('DPST-17-1','DPST-18-1'):
                            used = True
                            ga = "17.001"
                            if address['DatapointType'] == 'DPST-18-1':
                                ga="18.001"
                            
                            for description in descriptions:
                                if description.startswith('mappings='):
                                    mappings = description
                                    break

                            if mappings!= '':
                                #TODO: Mappings noch über metadata abbilden
                                mapfile = f"gen_{item_name}.map"
                                mappings = mappings.replace("'",'"')

                                mapfile_content = mappings.replace('"','').replace(',','\n').replace('mappings=[','').replace(']','').replace(' ','')
                                mapfile_content += '\n' + mapfile_content.replace('=','.0=') + '\n-=unknown'
                                open(os.path.join(config['transform_dir_path'], mapfile),'w').write(mapfile_content)

                                auto_add = True
                                item_type = "Number"
                                thing_address_info = f"ga=\"{ga}:{address['Address']}\""
                                item_label = f"{lovely_name} [MAP({mapfile}):%s]"
                                semantic_info = "[\"Control\"]"
                                item_icon = "movecontrol"
                                sitemap_type = "Selection"
                            else:
                                print(f"no mapping for scene {address['Address']} {address['Group name']} ")
                            #else:
                            #    items += f"Number        {item_name}         \"{lovely_name} [%d]\"                <movecontrol>          {{ channel=\"knx:device:bridge:generic:{item_name}\" }}\n"
                            #    group += f"        Selection item={item_name} label=\"{lovely_name}\"  {visibility}\n"
                            
                        # Szenensteuerung
                        #if address['DatapointType'] == 'DPST-18-1':
                        #    print(address)
                        #    used = True
                        #    things += f"Type number        : {item_name}        \"{address['Group name']}\"       [ ga=\"18.001:{address['Address']}\" ]\n"
                        #    items += f"Number        {item_name}         \"{lovely_name} [%d]\"                <sun>  (map{floorNr}_{roomNr})        {{ channel=\"knx:device:bridge:generic:{item_name}\" }}\n"

                        # Status
                        if address['DatapointType'] == 'DPST-1-11':
                            auto_add = True
                            item_type = "Switch"
                            thing_address_info = f"ga=\"1.011:{address['Address']}\""
                            item_label = f"{lovely_name}" # [%d]
                            semantic_info = "[\"Measurement\", \"Status\"]"
                            item_icon = "switch"
                        
                        # Betriebsartvorwahl 
                        if address['DatapointType'] == 'DPST-20-102':
                            auto_add = True
                            item_type = "Number:Dimensionless"
                            thing_address_info = f"ga=\"20.102:{address['Address']}\""
                            item_label = f"{lovely_name}"
                            semantic_info = "[\"HVAC\"]"
                            item_icon = "heating_mode"
                            metadata=", stateDescription=\"\"[options=\"NULL=unbekannt ...,1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"],commandDescription=\"\"[options=\"1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"]"
                        # Betriebsartvorwahl 
                        if address['DatapointType'] == 'DPST-5-010':
                            auto_add = True
                            item_type = "Number:Dimensionless"
                            thing_address_info = f"ga=\"5.010:{address['Address']}\""
                            item_label = f"{lovely_name}"
                            semantic_info = "[\"HVAC\"]"
                            item_icon = "heating_mode"
                            metadata=", stateDescription=\"\"[options=\"NULL=unbekannt ...,1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"],commandDescription=\"\"[options=\"1=Komfort,2=Standby,3=Nacht,4=Frostschutz\"]"                        

                    # TODO: get rid of this
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
                        # remove leading "[....]@"
                        item_label_short = re.sub('^\[\w*\]\@', '', item_label_short)
                        item_label_short = ' '.join(item_label_short.split())
                        if item_label_short != '':
                            item_label = item_label_short

                        if item_icon:
                            item_icon = f"<{item_icon}>"
                        else: 
                            item_icon = ""

                        item_label = item_label.replace(roomNameOrig, roomName)

                        thing_type = item_type.lower().split(":")[0]
                        things += f"Type {thing_type}    :   {item_name}   \"{address['Group name']}\"   [ {thing_address_info} ]\n"

                        root = f"map{floorNr}_{roomNr}"
                        if equipment != '':
                            items += f"Group   equipment_{item_name}   \"{item_label}\"  {item_icon}  ({root})   [\"{equipment}\"]\n"
                            root = f"equipment_{item_name}"

                        items += f"{item_type}   {item_name}   \"{item_label}\"   {item_icon}   ({root})   {semantic_info}    {{ channel=\"knx:device:bridge:generic:{item_name}\" {metadata}{synonyms} }}\n"
                        group += f"        {sitemap_type} item={item_name} label=\"{item_label}\" {mappings} {visibility}\n"

                        if 'influx' in address['Description']:
                            #print('influx @ ')
                            #print(address)
                            export_to_influx.append(item_name)

            if group != '':
                sitemap += f" {{\n{group}\n    }}\n"
            else:
                sitemap += f"\n "
        sitemap += f"}}\n "

def check_unusedAddresses():
    # process all addresses which were not used
    for floor in house:
        for room in floor['rooms']:
            addresses = room['Addresses']
            for i in range(len(addresses)):

                address = room['Addresses'][i]
                if 'IGNORE' in address.keys():
                    continue

                lovely_name = ' '.join(address['Group name'].replace(floor['Group name'],'').replace(room['Group name'],'').split())

                item_name = f"i_{cnt}_{floor['Group name']}_{room['Group name']}_{lovely_name}".replace('/','_').replace(' ','_')
                item_name = item_name.translate(special_char_map)

                if not (address['Address'] in used_addresses):
                    print(f"unused: {address['Address']}: {address['Group name']} with type {address['DatapointType']}")
                    
def export_output():
    global items,sitemap,things

    # export things:
    things_template = open('things.template','r').read()
    things = things_template.replace('###things###', things)
    os.makedirs(os.path.dirname(config['things_path']), exist_ok=True)
    open(config['things_path'],'w', encoding='utf8').write(things)
    # export items:
    items = 'Group           Home                  "Our Home"                                     [\"Location\"]\n' + items
    os.makedirs(os.path.dirname(config['items_path']), exist_ok=True)
    open(config['items_path'],'w', encoding='utf8').write(items)

    # export sitemap:
    sitemap_template_file = 'sitemap.template'
    if os.path.isfile(f"private_{sitemap_template_file}"):
        sitemap_template_file = f"private_{sitemap_template_file}"
    sitemap_template = open(sitemap_template_file,'r').read()
    sitemap = sitemap_template.replace('###sitemap###', sitemap)
    sitemap = sitemap.replace('###selections###', selections)
    os.makedirs(os.path.dirname(config['sitemaps_path']), exist_ok=True)
    open(config['sitemaps_path'],'w', encoding='utf8').write(sitemap)

    #export persistent
    private_persistence = ''
    if os.path.isfile(f"private_persistence"):
        private_persistence = open('private_persistence','r').read()
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


    print(fensterkontakte)
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
    os.makedirs(os.path.dirname('openhab/rules/fenster.rules'), exist_ok=True)
    open('openhab/rules/fenster.rules','w', encoding='utf8').write(fenster_rule)

def main():
    read_csvexport()
    genBuilding()
    check_unusedAddresses()
    export_output()

if __name__ == "__main__":
    main()
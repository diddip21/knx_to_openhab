#pip install xknxproject

"""Extract and parse a KNX project file."""
from xknxproject.models import KNXProject
from xknxproject import XKNXProj

import re, json

knxproj: XKNXProj = XKNXProj(
    #path="Charne.knxproj",
    path="Dr.knxproj",
    #password="password",  # optional
    #language="de-DE",  # optional
)
project: KNXProject = knxproj.parse()


def createBuilding(locations):
    if len(locations)==0:
        raise ValueError("'locations' is Empty.")
    prj = []
    pattern_item_Floor =re.compile(r"=[A-Z]+")
    pattern_item_Room =re.compile(r"\+?[A-Z].[0-9]+")
    pattern_floor_nameshort =re.compile(r'[A-Z]. ')
    iloc=0
    for loc in locations.values():
        if loc['type'] in ('Building','BuildingPart'):
            prj.insert(iloc,{
                'description':loc['description'],
                'name_long':loc['description'],
                'name_short':None,
                'floors':[]
                })
            prj_loc=prj[iloc]
        ifloor=0
        for floor in loc['spaces'].values():
            if floor['type'] in ('Floor','Stairway','Corridor'):
                prj_loc['floors'].insert(ifloor,{
                    'description':floor['description'],
                    'name_long':floor['description'],
                    'name_short':None,
                    'rooms':[]
                    })
                prj_floor=prj[iloc]['floors'][ifloor]
                res = pattern_floor_nameshort.search(floor['name'])
                if res is not None:
                    if res.group(0).startswith("="):
                        prj_floor['name_short']=res.group(0)
                    else:
                        prj_floor['name_short']="="+res.group(0)
                elif not floor['name'].startswith("=") and len(floor['name']) < 6:
                    prj_floor['name_short']="="+floor['name']
                    if prj_floor['description'] == '':
                        prj_floor['description']=floor['name']
                else:
                    prj_floor['description']=floor['name']
                    prj_floor['name_short']='='+floor['name']
                iroom=0
                for room in floor['spaces'].values():
                    if room['type'] == 'Room':
                        prj[iloc]['floors'][ifloor]['rooms'].insert(iroom,{
                            'description':room['description'],
                            'name_long':room['description'],
                            'name_short':None,
                        })
                        prj_room=prj[iloc]['floors'][ifloor]['rooms'][iroom]
                        resFloor = pattern_item_Floor.search(room['name'])
                        resRoom = pattern_item_Room.search(room['name'])
                        roomNamePlain = room['name']
                        roomNameLong = ''
                        if resFloor is not None:
                            roomNameLong+=resFloor.group(0)
                            roomNamePlain=str.replace(roomNamePlain,resFloor.group(0),"").strip()
                            if prj_floor['name_short']==floor['name'] or prj_floor['name_short']=="="+floor['name']:
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
                    iroom+=1
                if prj_floor['name_long'] == '':
                    prj_floor['name_long']=prj_floor['name_short']
                #print(f"Floor: {floor['name']} -> {floor['name_short']} - {floor['name_long']}")
            ifloor+=1
        iloc+=1
    return prj

prj=createBuilding(project['locations'])
pretty = json.dumps(prj, indent=2)#, sort_keys=True)
print(pretty)

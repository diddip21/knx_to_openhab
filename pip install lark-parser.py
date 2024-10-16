from lark import Lark, Transformer, v_args

# Define the grammar
grammar = r"""
    start: item+

    item: type identifier label? icon? groups? tags? metadata?
    type: "Group" membertype? aggfunc? aggargs?
        | "Number" membertype?
        | "Switch"
        | "Rollershutter"
        | "String"
        | "Dimmer"
        | "Contact"
        | "DateTime"
        | "Color"
        | "Player"
        | "Location"
        | "Call"
        | "Image"
    membertype: ":" CNAME
    aggfunc: ":" aggfuncname
    aggargs: "(" CNAME ("," CNAME)* ")"
    identifier: CNAME
    label: ESCAPED_STRING
    icon: "<" CNAME ">"
    groups: "(" CNAME ("," CNAME)* ")"
    tags: "[" (CNAME | ESCAPED_STRING) ("," (CNAME | ESCAPED_STRING))* "]"
    metadata: "{" metadata_entry ("," metadata_entry)* "}"
    metadata_entry: CNAME "=" (ESCAPED_STRING | SIGNED_NUMBER | metadata_config)
    metadata_config: "[" metadata_config_item ("," metadata_config_item)* "]"
    metadata_config_item: CNAME "=" (ESCAPED_STRING | SIGNED_NUMBER)

    aggfuncname: "AVG" | "SUM" | "MIN" | "MAX" | "OR" | "AND" | "NOR" | "NAND" | "COUNT" | "LATEST" | "EARLIEST" | "EQUALITY"

    %import common.CNAME
    %import common.ESCAPED_STRING
    %import common.SIGNED_NUMBER
    %import common.WS
    %ignore WS
"""

# Create the parser
parser = Lark(grammar, start='start', parser='lalr', transformer=None)

# Define transformer to convert parsed output to dictionary
@v_args(inline=True)
class ItemsTransformer(Transformer):
    def start(self, *items):
        return list(items)

    def item(self, item_type, identifier, label=None, icon=None, groups=None, tags=None, metadata=None):
        return {
            'type': item_type,
            'name': identifier,
            'label': label,
            'icon': icon,
            'groups': groups,
            'tags': tags,
            'metadata': metadata,
        }

    def type(self, *args):
        return ' '.join(args)

    def identifier(self, token):
        return str(token)

    def label(self, token):
        return str(token)[1:-1]  # Remove surrounding quotes

    def icon(self, token):
        return str(token)

    def groups(self, *tokens):
        return list(tokens)

    def tags(self, *tokens):
        return list(tokens)

    def metadata(self, *tokens):
        return dict(tokens)

    def metadata_entry(self, key, value):
        return (str(key), str(value)[1:-1] if isinstance(value, str) else value)

    def metadata_config(self, *items):
        return dict(items)

    def metadata_config_item(self, key, value):
        return (str(key), str(value)[1:-1] if isinstance(value, str) else value)

    def membertype(self, token):
        return str(token)

    def aggfunc(self, token):
        return str(token)

    def aggargs(self, *tokens):
        return list(tokens)

    def aggfuncname(self, token):
        return str(token)

# Create the transformer
transformer = ItemsTransformer()

# Example input string
input_str = """
Rollershutter   i_OG_RM5_0303OGRaffstoreREM2JalousieJalousieAufAb   "Schlafen-OG Raffstore Schlafen RE (-M2) Jalousie"   <rollershutter>   (equipment_i_OG_RM5_0303OGRaffstoreREM2JalousieJalousieAufAb)   ["Blinds"]    { channel="knx:device:bridge:generic:i_OG_RM5_0303OGRaffstoreREM2JalousieJalousieAufAb" , homekit = "CurrentPosition, TargetPosition, PositionState" [instance=2] }
Dimmer   i_OG_RM5_0303OGRaffstoreREM2JalousieAbsoluteLamellenposition   "Schlafen-OG Raffstore Schlafen RE (-M2) Jalousie"   <rollershutter>   (equipment_i_OG_RM5_0303OGRaffstoreREM2JalousieJalousieAufAb)   ["Blinds"]    { channel="knx:device:bridge:generic:i_OG_RM5_0303OGRaffstoreREM2JalousieAbsoluteLamellenposition" , homekit = "CurrentHorizontalTiltAngle, TargetHorizontalTiltAngle" [instance=2] }
"""

# Parse and transform the input string
parsed_tree = parser.parse(input_str)
transformed_data = transformer.transform(parsed_tree)

# Print the output
import pprint
pprint.pprint(transformed_data)

#!/usr/bin/python
# -*- encoding: utf-8; py-indent-offset: 4 -*-
# +------------------------------------------------------------------+
# |             ____ _               _        __  __ _  __           |
# |            / ___| |__   ___  ___| | __   |  \/  | |/ /           |
# |           | |   | '_ \ / _ \/ __| |/ /   | |\/| | ' /            |
# |           | |___| | | |  __/ (__|   <    | |  | | . \            |
# |            \____|_| |_|\___|\___|_|\_\___|_|  |_|_|\_\           |
# |                                                                  |
# | Copyright Mathias Kettner 2014             mk@mathias-kettner.de |
# +------------------------------------------------------------------+
#
# This file is part of Check_MK.
# The official homepage is at http://mathias-kettner.de/check_mk.
#
# check_mk is free software;  you can redistribute it and/or modify it
# under the  terms of the  GNU General Public License  as published by
# the Free Software Foundation in version 2.  check_mk is  distributed
# in the hope that it will be useful, but WITHOUT ANY WARRANTY;  with-
# out even the implied warranty of  MERCHANTABILITY  or  FITNESS FOR A
# PARTICULAR PURPOSE. See the  GNU General Public License for more de-
# ails.  You should have  received  a copy of the  GNU  General Public
# License along with GNU Make; see the file  COPYING.  If  not,  write
# to the Free Software Foundation, Inc., 51 Franklin St,  Fifth Floor,
# Boston, MA 02110-1301 USA.

# Frequently used variable names:
# perf_data_string:   Raw performance data as sent by the core, e.g "foor=17M;1;2;4;5"
# perf_data:          Split performance data, e.g. [("foo", "17", "M", "1", "2", "4", "5")]
# translated_metrics: Completely parsed and translated into metrics, e.g. { "foo" : { "value" : 17.0, "unit" : { "render" : ... }, ... } }
# color:              RGB color representation ala HTML, e.g. "#ffbbc3" or "#FFBBC3", len() is always 7!
# color_rgb:          RGB color split into triple (r, g, b), where r,b,g in (0.0 .. 1.0)
# unit_name:          The ID of a unit, e.g. "%"
# unit:               The definition-dict of a unit like in unit_info
# graph_template:     Template for a graph. Essentially a dict with the key "metrics"

import math, time, colorsys
import config, defaults, pagetypes, table
from lib import *
from valuespec import *
import livestatus


#   .--Plugins-------------------------------------------------------------.
#   |                   ____  _             _                              |
#   |                  |  _ \| |_   _  __ _(_)_ __  ___                    |
#   |                  | |_) | | | | |/ _` | | '_ \/ __|                   |
#   |                  |  __/| | |_| | (_| | | | | \__ \                   |
#   |                  |_|   |_|\__,_|\__, |_|_| |_|___/                   |
#   |                                 |___/                                |
#   +----------------------------------------------------------------------+
#   |  Typical code for loading Multisite plugins of this module           |
#   '----------------------------------------------------------------------'
# Datastructures and functions needed before plugins can be loaded
loaded_with_language = False

def load_plugins():
    global loaded_with_language

    if loaded_with_language == current_language:
        return

    global unit_info       ; unit_info       = {}
    global metric_info     ; metric_info     = {}
    global check_metrics   ; check_metrics   = {}
    global perfometer_info ; perfometer_info = []
    global graph_info      ; graph_info      = []
    load_web_plugins("metrics", globals())
    loaded_with_language = current_language


#.
#   .--Constants-----------------------------------------------------------.
#   |              ____                _              _                    |
#   |             / ___|___  _ __  ___| |_ __ _ _ __ | |_ ___              |
#   |            | |   / _ \| '_ \/ __| __/ _` | '_ \| __/ __|             |
#   |            | |__| (_) | | | \__ \ || (_| | | | | |_\__ \             |
#   |             \____\___/|_| |_|___/\__\__,_|_| |_|\__|___/             |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  Various constants to be used by the declarations of the plugins.    |
#   '----------------------------------------------------------------------'

KB = 1024
MB = KB * 1024
GB = MB * 1024
TB = GB * 1024
PB = TB * 1024

m = 0.001
K = 1000
M = K * 1000
G = M * 1000
T = G * 1000
P = T * 1000

scale_symbols = {
  m  : "m",
  1  : "",
  KB : "k",
  MB : "M",
  GB : "G",
  TB : "T",
  PB : "P",
  K  : "k",
  M  : "M",
  G  : "G",
  T  : "T",
  P  : "P",
}

scalar_colors = {
    "warn" : "#ffff00",
    "crit" : "#ff0000",
}


#.
#   .--Helpers-------------------------------------------------------------.
#   |                  _   _      _                                        |
#   |                 | | | | ___| |_ __   ___ _ __ ___                    |
#   |                 | |_| |/ _ \ | '_ \ / _ \ '__/ __|                   |
#   |                 |  _  |  __/ | |_) |  __/ |  \__ \                   |
#   |                 |_| |_|\___|_| .__/ \___|_|  |___/                   |
#   |                              |_|                                     |
#   +----------------------------------------------------------------------+
#   |  Various helper functions                                            |
#   '----------------------------------------------------------------------'

# "45.0" -> 45.0, "45" -> 45
def float_or_int(v):
    try:
        return int(v)
    except:
        return float(v)

def metric_to_text(metric, value=None):
    if value == None:
        value = metric["value"]
    return metric["unit"]["render"](value)

# A few helper function to be used by the definitions

#.
#   .--Colors--------------------------------------------------------------.
#   |                      ____      _                                     |
#   |                     / ___|___ | | ___  _ __ ___                      |
#   |                    | |   / _ \| |/ _ \| '__/ __|                     |
#   |                    | |__| (_) | | (_) | |  \__ \                     |
#   |                     \____\___/|_|\___/|_|  |___/                     |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  Functions and constants dealing with colors                         |
#   '----------------------------------------------------------------------'

cmk_color_palette = {
# do not use:
#   "0"     : (0.33, 1, 1),  # green
#   "1"     : (0.167, 1, 1), # yellow
#   "2"     : (0, 1, 1),     # red
# red area
    "11"    : (0.775, 1, 1),
    "12"    : (0.8, 1, 1),
    "13"    : (0.83, 1, 1),
    "14"    : (0.05, 1, 1),
    "15"    : (0.08, 1, 1),
    "16"    : (0.105, 1, 1),
# yellow area
    "21"    : (0.13, 1, 1),
    "22"    : (0.14, 1, 1),
    "23"    : (0.155, 1, 1),
    "24"    : (0.185, 1, 1),
    "25"    : (0.21, 1, 1),
    "26"    : (0.25, 1, 1),
# green area
    "31"    : (0.45, 1, 1),
    "32"    : (0.5, 1, 1),
    "33"    : (0.515, 1, 1),
    "34"    : (0.53, 1, 1),
    "35"    : (0.55, 1, 1),
    "36"    : (0.57, 1, 1),
# blue area
    "41"    : (0.59, 1, 1),
    "42"    : (0.62, 1, 1),
    "43"    : (0.66, 1, 1),
    "44"    : (0.71, 1, 1),
    "45"    : (0.73, 1, 1),
    "46"    : (0.75, 1, 1),
# special colors
    "51"    : (0, 0, 0.5),        # grey_50
    "52"    : (0.067, 0.7, 0.5),  # brown 1
    "53"    : (0.083, 0.8, 0.55), # brown 2
}

def get_palette_color_by_index(i, shading='a'):
    color_key = sorted(cmk_color_palette.keys())[i % len(cmk_color_palette)]
    return "%s/%s" % (color_key, shading)


# 23/c -> #ff8040
# #ff8040 -> #ff8040
def parse_color_into_hexrgb(color_string):
    if color_string[0] == "#":
        return color_string
    elif "/" in color_string:
        cmk_color_index, color_shading = color_string.split("/")
        hsv = list(cmk_color_palette[cmk_color_index])

        # Colors of the yellow ("2") and green ("3") area need to be darkened (in third place of the hsv tuple),
        # colors of the red and blue area need to be brightened (in second place of the hsv tuple).
        # For both shadings we need different factors.
        cmk_color_nuance_index = 1
        cmk_color_nuance_factor = 0.6

        if cmk_color_index[0] in ["2", "3"]:
            cmk_color_nuance_index = 2
            cmk_color_nuance_factor = 0.8

        if color_shading == 'b':
            hsv[cmk_color_nuance_index] *= cmk_color_nuance_factor

        color_hexrgb = hsv_to_hexrgb(hsv)
        return color_hexrgb
    else:
        return "#808080"


def hsv_to_hexrgb(hsv):
    return render_color(colorsys.hsv_to_rgb(*hsv))


# "#ff0080" -> (1.0, 0.0, 0.5)
def parse_color(color):
    try:
        return tuple([ int(color[a:a+2], 16) / 255.0 for a in (1,3,5) ])
    except Exception, e:
        raise MKGeneralException(_("Invalid color specification '%s'") % color)


def render_color(color_rgb):
    return "#%02x%02x%02x" % (
       int(color_rgb[0] * 255),
       int(color_rgb[1] * 255),
       int(color_rgb[2] * 255),)

# Make a color darker. v ranges from 0 (not darker) to 1 (black)
def darken_color(rgb, v):
    def darken(x, v):
        return x * (1.0 - v)
    return tuple([ darken(x, v) for x in rgb ])

# Make a color lighter. v ranges from 0 (not lighter) to 1 (white)
def lighten_color(rgb, v):
    def lighten(x, v):
        return x + ((1.0 - x) * v)
    return tuple([ lighten(x, v) for x in rgb ])

def mix_colors(a, b):
    return tuple([
       (ca + cb) / 2.0
       for (ca, cb)
       in zip(a, b)
    ])


#.
#   .--Evaluation----------------------------------------------------------.
#   |          _____            _             _   _                        |
#   |         | ____|_   ____ _| |_   _  __ _| |_(_) ___  _ __             |
#   |         |  _| \ \ / / _` | | | | |/ _` | __| |/ _ \| '_ \            |
#   |         | |___ \ V / (_| | | |_| | (_| | |_| | (_) | | | |           |
#   |         |_____| \_/ \__,_|_|\__,_|\__,_|\__|_|\___/|_| |_|           |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  Parsing of performance data into metrics, evaluation of expressions |
#   '----------------------------------------------------------------------'

# Convert perf_data_string into perf_data, extract check_command
def parse_perf_data(perf_data_string, check_command=None):
    # Strip away arguments like in "check_http!-H mathias-kettner.de"
    check_command = check_command.split("!")[0]

    if not perf_data_string:
        return None, check_command

    parts = perf_data_string.split()

    # Try if check command is appended to performance data
    # in a PNP like style
    if parts[-1].startswith("[") and parts[-1].endswith("]"):
        check_command = parts[-1][1:-1]
        del parts[-1]

    # Python's isdigit() works only on str. We deal with unicode since
    # we deal with data coming from Livestatus
    def isdigit(x):
        return x in [ '0', '1', '2', '3', '4', '5', '6', '7', '8', '9' ]

    # Parse performance data, at least try
    try:
        perf_data = []
        for part in parts:
            varname, values = part.split("=")
            value_parts = values.split(";")
            while len(value_parts) < 5:
                value_parts.append(None)
            value_text, warn, crit, min, max = value_parts[0:5]
            if value_text == "":
                continue # ignore useless empty variable

            # separate value from unit
            i = 0
            while i < len(value_text) and (isdigit(value_text[i]) or value_text[i] in ['.', ',', '-']):
                i += 1
            unit_name = value_text[i:]
            value = value_text[:i]
            perf_data.append((varname, value, unit_name, warn, crit, min, max))
    except:
        if config.debug:
            raise
        perf_data = None

    return perf_data, check_command



# Convert Ascii-based performance data as output from a check plugin
# into floating point numbers, do scaling if neccessary.
# Simple example for perf_data: [(u'temp', u'48.1', u'', u'70', u'80', u'', u'')]
# Result for this example:
# { "temp" : "value" : 48.1, "warn" : 70, "crit" : 80, "unit" : { ... } }
def translate_metrics(perf_data, check_command):
    cm = check_metrics.get(check_command, {})

    translated_metrics = {}
    color_index = 0
    for nr, entry in enumerate(perf_data):
        varname = entry[0]
        value_text = entry[1]

        translation_entry = {} # Default: no translation neccessary

        if varname in cm:
            translation_entry = cm[varname]
        else:
            for orig_varname, te in cm.items():
                if orig_varname[0] == "~" and regex(orig_varname[1:]).match(varname): # Regex entry
                    translation_entry = te
                    break


        # Translate name
        metric_name = translation_entry.get("name", varname)
        if metric_name in translated_metrics:
            continue # ignore duplicate value

        if metric_name not in metric_info:
            color_index += 1
            palette_color = get_palette_color_by_index(color_index)
            mi = {
                "title" : metric_name.title(),
                "unit" : "",
                "color" : parse_color_into_hexrgb(palette_color),
            }
        else:
            mi = metric_info[metric_name].copy()
            mi["color"] = parse_color_into_hexrgb(mi["color"])

        # Optional scaling
        scale = translation_entry.get("scale", 1.0)

        new_entry = {
            "value"      : float_or_int(value_text) * scale,
            "orig_name"  : varname,
            "scale"      : scale, # needed for graph definitions
            "scalar"     : {},
        }

        # Do not create graphs for ungraphed metrics if listed here
        new_entry["auto_graph"] = translation_entry.get("auto_graph", True)

        # Add warn, crit, min, max
        for index, key in [ (3, "warn"), (4, "crit"), (5, "min"), (6, "max") ]:
            if len(entry) < index + 1:
                break
            elif entry[index]:
                try:
                    value = float_or_int(entry[index])
                    new_entry["scalar"][key] = value * scale
                except:
                    if config.debug:
                        raise
                    pass # empty of invalid number


        new_entry.update(mi)
        new_entry["unit"] = unit_info[new_entry["unit"]]
        translated_metrics[metric_name] = new_entry
        # TODO: warn, crit, min, max
        # if entry[2]:
        #     # TODO: lower and upper levels
        #     translated_metrics[metric_name]["warn"] = float(entry[2])
    return translated_metrics


# Evaluates an expression, returns a triple of value, unit and color.
# e.g. "fs_used:max"    -> 12.455, "b", "#00ffc6",
# e.g. "fs_used(%)"     -> 17.5,   "%", "#00ffc6",
# e.g. "fs_used:max(%)" -> 100.0,  "%", "#00ffc6",
# e.g. 123.4            -> 123.4,  "",  None
# e.g. "123.4#ff0000"   -> 123.4,  "",  "#ff0000",
# Note:
# "fs_growth.max" is the same as fs_growth. The .max is just
# relevant when fetching RRD data and is used for selecting
# the consolidation function MAX.
def evaluate(expression, translated_metrics):
    if type(expression) in (float, int):
        return evaluate_literal(expression, translated_metrics)
    else:
        if "#" in expression:
            expression, explicit_color = expression.rsplit("#", 1) # drop appended color information
        else:
            explicit_color = None

        if "@" in expression:
            expression, explicit_unit_name = expression.rsplit("@", 1) # appended unit name
        else:
            explicit_unit_name = None

        value, unit, color = evaluate_rpn(expression, translated_metrics)

        if explicit_color:
            color = "#" + explicit_color

        if explicit_unit_name:
            unit = unit_info[explicit_unit_name]

        return value, unit, color


# TODO: real unit computation!
def unit_mult(u1, u2):
    if u1 == unit_info[""] or u1 == unit_info["count"]:
        return u2
    else:
        return u1

unit_div = unit_mult
unit_add = unit_mult
unit_sub = unit_mult

def operator_minmax(a, b, func):
    v = func(a[0], b[0])
    # Use unit and color of the winner. If the winner
    # has none (e.g. it is a scalar like 0), then take
    # unit and color of the loser.
    if v == a[0]:
        winner = a
        loser = b
    else:
        winner = b
        loser = a

    if winner[1] != unit_info[""]:
        unit = winner[1]
    else:
        unit = loser[1]

    return v, unit, winner[2] or loser[2]


# TODO: Do real unit computation, detect non-matching units
rpn_operators = {
    "+"  : lambda a, b: ((a[0] +  b[0]),                unit_mult(a[1], b[1]), choose_operator_color(a[2], b[2])),
    "-"  : lambda a, b: ((a[0] -  b[0]),                unit_sub(a[1], b[1]), choose_operator_color(a[2], b[2])),
    "*"  : lambda a, b: ((a[0] *  b[0]),                unit_add(a[1], b[1]), choose_operator_color(a[2], b[2])),
    "/"  : lambda a, b: ((a[0] /  b[0]),                unit_div(a[1], b[1]), choose_operator_color(a[2], b[2])),
    ">"  : lambda a, b: ((a[0] >  b[0] and 1.0 or 0.0), unit_info[""],         "#000000"),
    "<"  : lambda a, b: ((a[0] <  b[0] and 1.0 or 0.0), unit_info[""],         "#000000"),
    ">=" : lambda a, b: ((a[0] >= b[0] and 1.0 or 0.0), unit_info[""],         "#000000"),
    "<=" : lambda a, b: ((a[0] <= b[0] and 1.0 or 0.0), unit_info[""],         "#000000"),
    "MIN" : lambda a, b: operator_minmax(a, b, min),
    "MAX" : lambda a, b: operator_minmax(a, b, max),
}

def choose_operator_color(a, b):
    if a == None:
        return b
    elif b == None:
        return a
    else:
        return render_color(mix_colors(parse_color(a), parse_color(b)))


def evaluate_rpn(expression, translated_metrics):
    parts = expression.split(",")
    stack = [] # stack tuples of (value, unit, color)
    while parts:
        operator_name = parts[0]
        parts = parts[1:]
        if operator_name in rpn_operators:
            if len(stack) < 2:
                raise MKGeneralException("Syntax error in expression '%s': too few operands" % expression)
            op1 = stack[-2]
            op2 = stack[-1]
            result = rpn_operators[operator_name](op1, op2)
            stack = stack[:-2] + [ result ]
        else:
            stack.append(evaluate_literal(operator_name, translated_metrics))

    if len(stack) != 1:
        raise MKGeneralException("Syntax error in expression '%s': too many operands left" % expression)

    return stack[0]


def evaluate_literal(expression, translated_metrics):

    if type(expression) == int:
        return float(expression), unit_info["count"], None

    elif type(expression) == float:
        return expression, unit_info[""], None

    elif expression[0].isdigit() or expression[0] == '-':
        return float(expression), unit_info[""], None

    if expression.endswith(".max") or expression.endswith(".min") or expression.endswith(".average"):
        expression = expression.rsplit(".", 1)[0]

    color = None

    # TODO: Error handling with useful exceptions
    if expression.endswith("(%)"):
        percent = True
        expression = expression[:-3]
    else:
        percent = False

    if ":" in expression:
        varname, scalarname = expression.split(":")
        value = translated_metrics[varname]["scalar"].get(scalarname)
        color = scalar_colors.get(scalarname)
    else:
        varname = expression
        value = translated_metrics[varname]["value"]

    if percent:
        maxvalue = translated_metrics[varname]["scalar"]["max"]
        if maxvalue != 0:
           value = 100.0 * float(value) / maxvalue
        else:
           value = 0.0
        unit = unit_info["%"]

    else:
        unit = translated_metrics[varname]["unit"]

    if color == None:
        color = parse_color_into_hexrgb(metric_info[varname]["color"])
    return value, unit, color


# Replace expressions in strings like CPU Load - %(load1:max@count) CPU Cores"
def replace_expressions(text, translated_metrics):
    def eval_to_string(match):
        expression = match.group()[2:-1]
        unit_name = None
        if "@" in expression:
            expression, unit_name = expression.split("@")
        value, unit, color = evaluate(expression, translated_metrics)
        if unit_name:
            unit = unit_info[unit_name]
        if value != None:
            return unit["render"](value)
        else:
            return _("n/a")

    r = regex(r"%\([^)]*\)")
    return r.sub(eval_to_string, text)

#.
#   .--Perf-O-Meters-------------------------------------------------------.
#   |  ____            __        ___        __  __      _                  |
#   | |  _ \ ___ _ __ / _|      / _ \      |  \/  | ___| |_ ___ _ __ ___   |
#   | | |_) / _ \ '__| |_ _____| | | |_____| |\/| |/ _ \ __/ _ \ '__/ __|  |
#   | |  __/  __/ |  |  _|_____| |_| |_____| |  | |  __/ ||  __/ |  \__ \  |
#   | |_|   \___|_|  |_|        \___/      |_|  |_|\___|\__\___|_|  |___/  |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  Implementation of Perf-O-Meters                                     |
#   '----------------------------------------------------------------------'

def get_perfometers(translated_metrics):
    for perfometer in perfometer_info:
        if perfometer_possible(perfometer, translated_metrics):
            yield perfometer


# TODO: We will run into a performance problem here when we
# have more and more Perf-O-Meter definitions.
# TODO: remove all tuple-perfometers and use dicts
def perfometer_possible(perfometer, translated_metrics):

    if type(perfometer) == dict:
        if perfometer["type"] == "linear":
            required = perfometer["segments"][:]
        elif perfometer["type"] == "logarithmic":
            required = [ perfometer["metric"] ]
        else:
            pass # TODO: dual, stacked?

        if "label" in perfometer and perfometer["label"] != None:
            required.append(perfometer["label"][0])
        if "total" in perfometer:
            required.append(perfometer["total"])

        for req in required:
            try:
                evaluate(req, translated_metrics)
            except:
                return False

        if "condition" in perfometer:
            try:
                value, color, unit = evaluate(perfometer["condition"], translated_metrics)
                if value == 0.0:
                    return False
            except:
                return False

        return True



    perf_type, perf_args = perfometer

    if perf_type == "logarithmic":
        required = [ perf_args[0] ]

    elif perf_type == "linear":
        required = perf_args[0]
        if perf_args[1]:
            required = required + [perf_args[1]] # Reference value for 100%
        if perf_args[2]:
            required = required + [perf_args[2]] # Labelling value

    elif perf_type in ("stacked", "dual"):
        for sub_perf in perf_args:
            if not perfometer_possible(sub_perf, translated_metrics):
                return False
        return True

    else:
        raise MKInternalError(_("Undefined Perf-O-Meter type '%s'") % perf_type)

    for req in required:
        try:
            evaluate(req, translated_metrics)
        except:
            return False
    return True


def metricometer_logarithmic(value, half_value, base, color):
    # Negative values are printed like positive ones (e.g. time offset)
    value = abs(float(value))
    if value == 0.0:
        pos = 0
    else:
        half_value = float(half_value)
        h = math.log(half_value, base) # value to be displayed at 50%
        pos = 50 + 10.0 * (math.log(value, base) - h)
        if pos < 2:
            pos = 2
        if pos > 98:
            pos = 98

    return [ (pos, color), (100 - pos, "#ffffff") ]


def build_perfometer(perfometer, translated_metrics):
    # TODO: alle nicht-dict Perfometer umstellen
    if type(perfometer) == dict:
        if perfometer["type"] == "logarithmic":
            value, unit, color = evaluate(perfometer["metric"], translated_metrics)
            label = unit["render"](value)
            stack = [ metricometer_logarithmic(value, perfometer["half_value"], perfometer["exponent"], color) ]

        elif perfometer["type"] == "linear":
            entry = []
            stack = [entry]

            summed = 0.0

            for ex in perfometer["segments"]:
                value, unit, color = evaluate(ex, translated_metrics)
                summed += value

            if "total" in perfometer:
                total, unit, color = evaluate(perfometer["total"], translated_metrics)
            else:
                total = summed

            if total == 0:
                entry.append((100.0, "#ffffff"))

            else:
                for ex in perfometer["segments"]:
                    value, unit, color = evaluate(ex, translated_metrics)
                    entry.append((100.0 * value / total, color))

                # Paint rest only, if it is positive and larger than one promille
                if total - summed > 0.001:
                    entry.append((100.0 * (total - summed) / total, "#ffffff"))

            # Use unit of first metrics for output of sum. We assume that all
            # stackes metrics have the same unit anyway
            value, unit, color = evaluate(perfometer["segments"][0], translated_metrics)
            label = unit["render"](summed)

        # "label" option in all Perf-O-Meters overrides automatic label
        if "label" in perfometer:
            if perfometer["label"] == None:
                label = ""
            else:
                expr, unit_name = perfometer["label"]
                value, unit, color = evaluate(expr, translated_metrics)
                if unit_name:
                    unit = unit_info[unit_name]
                label = unit["render"](value)

        return label, stack



    # This stuf is deprecated and will be removed soon. Watch out!
    perfometer_type, definition = perfometer

    if perfometer_type == "logarithmic":
        expression, median, exponent = definition
        value, unit, color = evaluate(expression, translated_metrics)
        label = unit["render"](value)
        stack = [ metricometer_logarithmic(value, median, exponent, color) ]

    # TODO: das hier fliegt raus
    elif perfometer_type == "linear":
        entry = []
        stack = [entry]

        # NOTE: This might be converted to a dict later.
        metrics_expressions, total_spec, label_expression = definition
        summed = 0.0

        for ex in metrics_expressions:
            value, unit_name, color = evaluate(ex, translated_metrics)
            summed += value

        if total_spec == None:
            total = summed
        else:
            total, unit_name, color = evaluate(total_spec, translated_metrics)

        if total == 0:
            entry.append((100.0, "#ffffff"))

        else:
            for ex in metrics_expressions:
                value, unit_name, color = evaluate(ex, translated_metrics)
                entry.append((100.0 * value / total, color))

            # Paint rest only, if it is positive and larger than one promille
            if total - summed > 0.001:
                entry.append((100.0 * (total - summed) / total, "#ffffff"))

        # Use unit of first metrics for output of sum. We assume that all
        # stackes metrics have the same unit anyway
        if label_expression:
            expr, unit_name = label_expression
            value, unit, color = evaluate(expr, translated_metrics)
            if unit_name:
                unit = unit_info[unit_name]
            label = unit["render"](summed)
        else: # absolute
            value, unit, color = evaluate(metrics_expressions[0], translated_metrics)
            label = unit["render"](summed)

    elif perfometer_type == "stacked":
        stack = []
        labels = []
        for sub_perf in definition:
            sub_label, sub_stack = build_perfometer(sub_perf, translated_metrics)
            stack.append(sub_stack[0])
            if sub_label:
                labels.append(sub_label)
        if labels:
            label = " / ".join(labels)
        else:
            label = ""
        return label, stack

    elif perfometer_type == "dual":
        labels = []
        if len(definition) != 2:
            raise MKInternalError(_("Perf-O-Meter of type 'dual' must contain exactly two definitions, not %d") % len(definition))

        content = []
        for nr, sub_perf in enumerate(definition):
            sub_label, sub_stack = build_perfometer(sub_perf, translated_metrics)
            if len(sub_stack) != 1:
                raise MKInternalError(_("Perf-O-Meter of type 'dual' must only contain plain Perf-O-Meters"))

            half_stack = [ (value/2, color) for (value, color) in sub_stack[0] ]
            if nr == 0:
                half_stack.reverse()
            content += half_stack
            if sub_label:
                labels.append(sub_label)

        if labels:
            label = " / ".join(labels)
        else:
            label = ""
        return label, [ content ]


    else:
        raise MKInternalError(_("Unsupported Perf-O-Meter type '%s'") % perfometer_type)

    return label, stack




#.
#   .--Graphs--------------------------------------------------------------.
#   |                    ____                 _                            |
#   |                   / ___|_ __ __ _ _ __ | |__  ___                    |
#   |                  | |  _| '__/ _` | '_ \| '_ \/ __|                   |
#   |                  | |_| | | | (_| | |_) | | | \__ \                   |
#   |                   \____|_|  \__,_| .__/|_| |_|___/                   |
#   |                                  |_|                                 |
#   +----------------------------------------------------------------------+
#   |  Implementation of time graphs - basic code, not the rendering       |
#   |  Rendering of the graphs is done by PNP4Nagios, we just create PHP   |
#   |  templates for PNP here.
#   '----------------------------------------------------------------------'

def get_graph_templates(translated_metrics):
    if not translated_metrics:
        return []

    explicit_templates = get_explicit_graph_templates(translated_metrics)
    already_graphed_metrics = get_graphed_metrics(explicit_templates)
    implicit_templates = get_implicit_graph_templates(translated_metrics, already_graphed_metrics)
    return explicit_templates + implicit_templates


def get_explicit_graph_templates(translated_metrics):
    templates = []
    for graph_template in graph_info:
        if graph_possible(graph_template, translated_metrics):
            templates.append(graph_template)
        elif graph_possible_without_optional_metrics(graph_template, translated_metrics):
            templates.append(graph_without_missing_optional_metrics(graph_template, translated_metrics))
    return templates


def get_implicit_graph_templates(translated_metrics, already_graphed_metrics):
    templates = []
    for metric_name, metric_entry in sorted(translated_metrics.items()):
        if metric_entry["auto_graph"] and metric_name not in already_graphed_metrics:
            templates.append(generic_graph_template(metric_name))
    return templates


def get_graphed_metrics(graph_templates):
    graphed_metrics = set([])
    for graph_template in graph_templates:
        graphed_metrics.update(metrics_used_by_graph(graph_template))
    return graphed_metrics


def metrics_used_by_graph(graph_template):
    used_metrics = []
    for metric_definition in graph_template["metrics"]:
        used_metrics += list(metrics_used_in_definition(metric_definition[0]))
    return used_metrics


def metrics_used_in_definition(metric_definition):
    without_unit = metric_definition.split("@")[0]
    without_color = metric_definition.split("#")[0]
    parts = without_color.split(",")
    for part in parts:
        metric_name = part.split(".")[0] # drop .min, .max, .average
        if metric_name in metric_info:
            yield metric_name


def graph_possible(graph_template, translated_metrics):
    for metric_definition in graph_template["metrics"]:
        try:
            evaluate(metric_definition[0], translated_metrics)
        except Exception, e:
            return False

    # Allow graphs to be disabled if certain (better) metrics
    # are available
    if "conflicting_metrics" in graph_template:
        for var in graph_template["conflicting_metrics"]:
            if var in translated_metrics:
                return False

    return True


def graph_possible_without_optional_metrics(graph_template, translated_metrics):
    if "optional_metrics" in graph_template:
        return graph_possible(graph_template,
                      add_fake_metrics(translated_metrics, graph_template["optional_metrics"]))


def graph_without_missing_optional_metrics(graph_template, translated_metrics):
    working_metrics = []

    for metric_definition in graph_template["metrics"]:
        try:
            evaluate(metric_definition[0], translated_metrics)
            working_metrics.append(metric_definition)
        except:
            pass

    reduced_graph_template = graph_template.copy()
    reduced_graph_template["metrics"] = working_metrics
    return reduced_graph_template


def add_fake_metrics(translated_metrics, metric_names):
    with_fake = translated_metrics.copy()
    for metric_name in metric_names:
        with_fake[metric_name] = {
            "value" : 1.0,
            "scale" : 1.0,
            "unit" : unit_info[""],
            "color" : "#888888",
        }
    return with_fake


def generic_graph_template(metric_name):
    return {
        "metrics" : [
            ( metric_name, "area" ),
        ],
        "scalars" : [
            metric_name + ":warn",
            metric_name + ":crit",
        ]
    }


def get_graph_range(graph_template, translated_metrics):
    if "range" in graph_template:
        min_value, max_value = [
            evaluate(r, translated_metrics)[0]
            for r in graph_template["range"]
        ]

    else:
        # Compute range of displayed data points
        max_value = None
        min_value = None

    return min_value, max_value


# Called with exactly one variable: the template ID. Example:
# "check_mk-kernel.util:guest,steal,system,user,wait".
def page_pnp_template():
    try:
        template_id = html.var("id")

        check_command, perf_var_string = template_id.split(":", 1)
        perf_var_names = perf_var_string.split(",")

        # Fake performance values in order to be able to find possible graphs
        perf_data = [ ( varname, 1, "", 1, 1, 1, 1 ) for varname in perf_var_names ]
        translated_metrics = translate_metrics(perf_data, check_command)
        if not translated_metrics:
            return # check not supported

        # Collect output in string. In case of an exception to not output
        # any definitions
        output = ""
        for graph_template in get_graph_templates(translated_metrics):
            graph_code = render_graph_pnp(graph_template, translated_metrics)
            output += graph_code

        html.write(output)

    except Exception, e:
        import traceback
        html.write("An error occured:\n%s\n" % traceback.format_exc())


# TODO: some_value.max not yet working
def render_graph_pnp(graph_template, translated_metrics):
    graph_title = None
    vertical_label = None

    rrdgraph_commands = ""

    legend_precision    = graph_template.get("legend_precision", 2)
    legend_scale        = graph_template.get("legend_scale", 1)
    legend_scale_symbol = scale_symbols[legend_scale]

    # Define one RRD variable for each of the available metrics.
    # Note: We need to use the original name, not the translated one.
    for var_name, metrics in translated_metrics.items():
        rrd = "$RRDBASE$_" + pnp_cleanup(metrics["orig_name"]) + ".rrd"
        scale = metrics["scale"]
        unit = metrics["unit"]
        render_scale = unit.get("render_scale", 1)

        if scale != 1.0 or render_scale != 1.0:
            rrdgraph_commands += "DEF:%s_UNSCALED=%s:1:MAX " % (var_name, rrd)
            rrdgraph_commands += "CDEF:%s=%s_UNSCALED,%f,* " % (var_name, var_name, scale * render_scale)

        else:
            rrdgraph_commands += "DEF:%s=%s:1:MAX " % (var_name, rrd)

        # Scaling for legend
        rrdgraph_commands += "CDEF:%s_LEGSCALED=%s,%f,/ " % (var_name, var_name, legend_scale)

        # Prepare negative variants for upside-down graph
        rrdgraph_commands += "CDEF:%s_NEG=%s,-1,* " % (var_name, var_name)
        rrdgraph_commands += "CDEF:%s_LEGSCALED_NEG=%s_LEGSCALED,-1,* " % (var_name, var_name)


    # Compute width of columns in case of mirrored legend

    total_width = 89 # characters
    left_width = max([len(_("Average")), len(_("Maximum")), len(_("Last"))]) + 2
    column_width = (total_width - left_width) / len(graph_template["metrics"]) - 2

    # Now add areas and lines to the graph
    graph_metrics = []

    # Graph with upside down metrics? (e.g. for Disk IO)
    have_upside_down = False

    # Compute width of the right column of the legend
    max_title_length = 0
    for nr, metric_definition in enumerate(graph_template["metrics"]):
        if len(metric_definition) >= 3:
            title = metric_definition[2]
        elif not "," in metric_definition:
            metric_name = metric_definition[0].split("#")[0]
            mi = translated_metrics[metric_name]
            title = mi["title"]
        else:
            title = ""
        max_title_length = max(max_title_length, len(title))


    for nr, metric_definition in enumerate(graph_template["metrics"]):
        metric_name = metric_definition[0]
        line_type = metric_definition[1] # "line", "area", "stack"

        # Optional title, especially for derived values
        if len(metric_definition) >= 3:
            title = metric_definition[2]
        else:
            title = ""

        # Prefixed minus renders the metrics in negative direction
        if line_type[0] == '-':
            have_upside_down = True
            upside_down = True
            upside_down_factor = -1
            line_type = line_type[1:]
            upside_down_suffix = "_NEG"
        else:
            upside_down = False
            upside_down_factor = 1
            upside_down_suffix = ""

        if line_type == "line":
            draw_type = "LINE"
            draw_stack = ""
        elif line_type == "area":
            draw_type = "AREA"
            draw_stack = ""
        elif line_type == "stack":
            draw_type = "AREA"
            draw_stack = ":STACK"

        # User can specify alternative color using a suffixed #aabbcc
        if '#' in metric_name:
            metric_name, custom_color = metric_name.split("#", 1)
        else:
            custom_color = None

        commands = ""
        # Derived value with RBN syntax (evaluated by RRDTool!).
        if "," in metric_name:
            # We evaluate just in order to get color and unit.
            # TODO: beware of division by zero. All metrics are set to 1 here.
            value, unit, color = evaluate(metric_name, translated_metrics)

            # Choose a unique name for the derived variable and compute it
            commands += "CDEF:DERIVED%d=%s " % (nr , metric_name)
            if upside_down:
                commands += "CDEF:DERIVED%d_NEG=DERIVED%d,-1,* " % (nr, nr)

            metric_name = "DERIVED%d" % nr
            # Scaling and upsidedown handling for legend
            commands += "CDEF:%s_LEGSCALED%s=%s,%f,/ " % (metric_name, upside_down_suffix, metric_name, legend_scale * upside_down_factor)

        else:
            mi = translated_metrics[metric_name]
            if not title:
                title = mi["title"]
            color = parse_color_into_hexrgb(mi["color"])
            unit = mi["unit"]

        if custom_color:
            color = "#" + custom_color

        # Paint the graph itself
        # TODO: Die Breite des Titels intelligent berechnen. Bei legend = "mirrored" muss man die
        # Vefügbare Breite ermitteln und aufteilen auf alle Titel
        right_pad = " " * (max_title_length - len(title))
        commands += "%s:%s%s%s:\"%s%s\"%s " % (draw_type, metric_name, upside_down_suffix, color, title.replace(":", "\\:"), right_pad, draw_stack)
        if line_type == "area":
            commands += "LINE:%s%s%s " % (metric_name, upside_down_suffix, render_color(darken_color(parse_color(color), 0.2)))

        unit_symbol = unit["symbol"]
        if unit_symbol == "%":
            unit_symbol = "%%"
        else:
            unit_symbol = " " + unit_symbol

        graph_metrics.append((metric_name, unit_symbol, commands))

        # Use title and label of this metrics as default for the graph
        if title and not graph_title:
            graph_title = title
        if not vertical_label:
            vertical_label = unit["title"]


    # Now create the rrdgraph commands for all metrics - according to the choosen layout
    for metric_name, unit_symbol, commands in graph_metrics:
        rrdgraph_commands += commands
        legend_symbol = unit_symbol
        if unit_symbol and unit_symbol[0] == " ":
            legend_symbol = " %s%s" % (legend_scale_symbol, unit_symbol[1:])
        for what, what_title in [ ("AVERAGE", _("average")), ("MAX", _("max")), ("LAST", _("last")) ]:
            rrdgraph_commands += "GPRINT:%%s_LEGSCALED:%%s:\"%%%%8.%dlf%%s %%s\" "  % legend_precision % \
                        (metric_name, what, legend_symbol, what_title)
        rrdgraph_commands += "COMMENT:\"\\n\" "


    # For graphs with both up and down, paint a gray rule at 0
    if have_upside_down:
        rrdgraph_commands += "HRULE:0#c0c0c0 "

    # Now compute the arguments for the command line of rrdgraph
    rrdgraph_arguments = ""

    graph_title = graph_template.get("title", graph_title)
    vertical_label = graph_template.get("vertical_label", vertical_label)

    rrdgraph_arguments += " --vertical-label %s --title %s " % (
        quote_shell_string(vertical_label or " "),
        quote_shell_string(graph_title))

    min_value, max_value = get_graph_range(graph_template, translated_metrics)
    if min_value != None and max_value != None:
        rrdgraph_arguments += " -l %f -u %f" % (min_value, max_value)
    else:
        rrdgraph_arguments += " -l 0"

    return graph_title + "\n" + rrdgraph_arguments + "\n" + rrdgraph_commands + "\n"


#.
#   .--Hover-Graph---------------------------------------------------------.
#   |     _   _                           ____                 _           |
#   |    | | | | _____   _____ _ __      / ___|_ __ __ _ _ __ | |__        |
#   |    | |_| |/ _ \ \ / / _ \ '__|____| |  _| '__/ _` | '_ \| '_ \       |
#   |    |  _  | (_) \ V /  __/ | |_____| |_| | | | (_| | |_) | | | |      |
#   |    |_| |_|\___/ \_/ \___|_|        \____|_|  \__,_| .__/|_| |_|      |
#   |                                                   |_|                |
#   '----------------------------------------------------------------------'


def new_style_graphs_possible():
    return browser_supports_canvas() and not html.is_mobile()


def browser_supports_canvas():
    user_agent = html.get_user_agent()
    if 'MSIE' in user_agent:
        matches = regex('MSIE ([0-9]{1,}[\.0-9]{0,})').search(user_agent)
        return not matches or float(matches.group(1)) >= 9.0
    else:
        return True


def page_show_graph():
    site = html.var('site')
    host_name = html.var('host_name')
    service = html.var('service')

    if new_style_graphs_possible():
        # FIXME HACK TODO We don't have the current perfata and check command
        # here, but we only need it till metrics.render_svc_time_graph() does
        # not need these information anymore.
        if service == "_HOST_":
            query = "GET hosts\n" \
                    "Filter: host_name = %s\n" \
                    "Columns: perf_data metrics check_command\n" % host_name

        else:
            query = "GET services\n" \
                    "Filter: host_name = %s\n" \
                    "Filter: service_description = %s\n" \
                    "Columns: perf_data metrics check_command\n" % (host_name, service)

        html.live.set_only_sites([site])
        try:
            data = html.live.query_row(query)
        except livestatus.MKLivestatusNotFoundError:
            html.write('<div class="error">%s</div>' %
                _('Failed to fetch data for graph. Maybe the site is not reachable?'))
            return
        html.live.set_only_sites(None)

        if service == "_HOST_":
            row = {
                'site'                  : site,
                'host_name'             : host_name,
                'host_perf_data'        : data[0],
                'host_metrics'          : data[1],
                'host_check_command'    : data[2],
            }
        else:
            row = {
                'site'                  : site,
                'host_name'             : host_name,
                'service_description'   : service,
                'service_perf_data'     : data[0],
                'service_metrics'       : data[1],
                'service_check_command' : data[2],
            }

        # now try to render the graph with our graphing. If it is not possible,
        # add JS code to let browser fetch the PNP graph
        try:
            # Currently always displaying 24h graph
            end_time = time.time()
            start_time = end_time - 8 * 3600

            htmlcode = render_time_graph(row, start_time, end_time, size=(30, 10), font_size=8, show_legend=False, graph_id_prefix="hover")
            if htmlcode:
                html.write(htmlcode)
                return
        except NameError:
            if config.debug:
                raise
            pass

    # Fallback to PNP graph rendering
    host = pnp_cleanup(host_name)
    svc = pnp_cleanup(service)
    site = html.site_status[site]["site"]
    if html.mobile:
        url = site["url_prefix"] + ("pnp4nagios/index.php?kohana_uri=/mobile/popup/%s/%s" % \
            (html.urlencode(host), html.urlencode(svc)))
    else:
        url = site["url_prefix"] + ("pnp4nagios/index.php/popup?host=%s&srv=%s" % \
            (html.urlencode(host), html.urlencode(svc)))

    html.write(url)

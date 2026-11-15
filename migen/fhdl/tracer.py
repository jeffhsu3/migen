import inspect
from sys import version_info
from opcode import opname
from collections import defaultdict

# All opcodes are 2 bytes in length in Python 3.6
def _bytecode_length_version_guard(old_len):
    return old_len if version_info[1] < 6 else 2

_call_opcodes = {
    "CALL_FUNCTION" : _bytecode_length_version_guard(3),
    "CALL_FUNCTION_KW" : _bytecode_length_version_guard(3),
}

if version_info[1] < 6:
    _call_opcodes["CALL_FUNCTION_VAR"] = 3
    _call_opcodes["CALL_FUNCTION_VAR_KW"] = 3
elif version_info[1] < 7:
    _call_opcodes["CALL_FUNCTION_EX"] = 2
else:
    _call_opcodes["CALL_FUNCTION_EX"] = 2
    _call_opcodes["CALL_METHOD"] = 2
    _call_opcodes["CALL_METHOD_KW"] = 2
    _call_opcodes["CALL"] = 2
    _call_opcodes["CALL_KW"] = 2

_load_build_opcodes = {
    "LOAD_GLOBAL" : _bytecode_length_version_guard(3),
    "LOAD_NAME" : _bytecode_length_version_guard(3),
    "LOAD_ATTR" : _bytecode_length_version_guard(3),
    "LOAD_FAST" : _bytecode_length_version_guard(3),
    "LOAD_DEREF" : _bytecode_length_version_guard(3),
    "DUP_TOP" : _bytecode_length_version_guard(1),
    "BUILD_LIST" : _bytecode_length_version_guard(3),
    "CACHE" : _bytecode_length_version_guard(3),
    "COPY" : _bytecode_length_version_guard(3),
}


_MISSING = object()
# Keyed by id(code) because CPython 3.11+ CodeType.__hash__ materializes and
# hashes de-quickened co_code on every lookup (expensive on large functions).
# Storing `code` inside each entry keeps the CodeType alive so id(code) is unique.
# Entry layout: [code, co_code_or_None, has_self, coname_or_None, raw_vns, clean_vns]
_code_cache = {}
_obj_tuple_cache = {}


def _get_code_entry(code):
    cid = id(code)
    entry = _code_cache.get(cid)
    if entry is None:
        has_self = _check_code_has_self(code)
        coname = code.co_name
        if coname == "<module>":
            coname = None
        else:
            coname = remove_underscore(coname)
        entry = [code, None, has_self, coname, {}, {}]
        _code_cache[cid] = entry
    return entry


def _scan_var_name(code, co_code, call_index):
    while call_index > 0 and opname[co_code[call_index]] == "CACHE":
        call_index -= 2
    while True:
        call_opc = opname[co_code[call_index]]
        if call_opc == "EXTENDED_ARG":
            call_index += 2
        else:
            break
    if call_opc not in _call_opcodes:
        return None
    index = call_index + _call_opcodes[call_opc]
    while True:
        opc = opname[co_code[index]]
        if opc == "STORE_NAME" or opc == "STORE_ATTR":
            name_index = co_code[index + 1]
            return code.co_names[name_index]
        elif opc == "STORE_FAST":
            name_index = co_code[index + 1]
            return code.co_varnames[name_index]
        elif opc == "STORE_DEREF":
            name_index = co_code[index + 1]
            if name_index < code.co_nlocals:
                return code.co_varnames[name_index]
            name_index -= code.co_nlocals
            if name_index < len(code.co_cellvars):
                return code.co_cellvars[name_index]
            name_index -= len(code.co_cellvars)
            return code.co_freevars[name_index]
        elif opc in _load_build_opcodes:
            index += _load_build_opcodes[opc]
        else:
            return None


def get_var_name(frame):
    code = frame.f_code
    entry = _get_code_entry(code)
    lasti = frame.f_lasti
    raw_vns = entry[4]
    vn = raw_vns.get(lasti, _MISSING)
    if vn is _MISSING:
        co_code = entry[1]
        if co_code is None:
            co_code = entry[1] = code.co_code
        vn = raw_vns[lasti] = _scan_var_name(code, co_code, lasti)
    return vn


def remove_underscore(s):
    if len(s) > 2 and s[0] == "_" and s[1] != "_":
        s = s[1:]
    return s


def get_obj_var_name(override=None, default=None):
    if override:
        return override

    frame = inspect.currentframe().f_back
    # We can be called via derived classes. Go back the stack frames
    # until we reach the first class that does not inherit from us.
    ourclass = frame.f_locals["self"].__class__
    while "self" in frame.f_locals and isinstance(frame.f_locals["self"], ourclass):
        frame = frame.f_back

    vn = get_var_name(frame)
    if vn is None:
        vn = default
    else:
        vn = remove_underscore(vn)
    return vn

name_to_idx = defaultdict(int)
# classname -> (objs, {id(obj): index})
# The objs list keeps references alive so ids stay unique.
classname_to_objs = dict()


def _obj_index(classname, obj):
    try:
        objs, obj_ids = classname_to_objs[classname]
    except KeyError:
        objs, obj_ids = [], {}
        classname_to_objs[classname] = (objs, obj_ids)
    i = id(obj)
    try:
        return obj_ids[i]
    except KeyError:
        idx = len(objs)
        obj_ids[i] = idx
        objs.append(obj)
        return idx


def _check_code_has_self(code):
    if not (code.co_flags & 2):
        return True
    return ("self" in code.co_varnames
            or "self" in code.co_cellvars
            or "self" in code.co_freevars)


def trace_back(varname=None):
    l = []
    if not classname_to_objs and _obj_tuple_cache:
        _obj_tuple_cache.clear()
    frame = inspect.currentframe().f_back.f_back
    while frame is not None:
        code = frame.f_code
        entry = _code_cache.get(id(code))
        if entry is None:
            entry = _get_code_entry(code)

        if varname is None:
            lasti = frame.f_lasti
            clean_vns = entry[5]
            varname = clean_vns.get(lasti, _MISSING)
            if varname is _MISSING:
                raw_vns = entry[4]
                raw_vn = raw_vns.get(lasti, _MISSING)
                if raw_vn is _MISSING:
                    co_code = entry[1]
                    if co_code is None:
                        co_code = entry[1] = code.co_code
                    raw_vn = raw_vns[lasti] = _scan_var_name(code, co_code, lasti)
                varname = remove_underscore(raw_vn) if raw_vn is not None else None
                clean_vns[lasti] = varname
            if varname is not None:
                l.append((varname, name_to_idx[varname]))
                name_to_idx[varname] += 1
        else:
            varname = remove_underscore(varname)
            l.append((varname, name_to_idx[varname]))
            name_to_idx[varname] += 1

        if entry[2]:
            obj = frame.f_locals.get("self")
            if obj is not None:
                oid = id(obj)
                tup = _obj_tuple_cache.get(oid)
                if tup is None:
                    if hasattr(obj, "__del__"):
                        obj = None
                    else:
                        raw_cls = obj.__class__.__name__.lower()
                        idx = _obj_index(raw_cls, obj)
                        tup = (remove_underscore(raw_cls), idx)
                        _obj_tuple_cache[oid] = tup
                if tup is not None:
                    l.append(tup)
                    varname = None
                    frame = frame.f_back
                    continue

        if varname is not None:
            coname = entry[3]
            if coname is None:
                modules = frame.f_globals["__name__"]
                coname = remove_underscore(modules.rsplit(".", 1)[-1])
            l.append((coname, name_to_idx[coname]))
            name_to_idx[coname] += 1

        varname = None
        frame = frame.f_back
    l.reverse()
    return l

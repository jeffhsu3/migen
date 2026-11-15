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
_var_name_cache = {}
_clean_var_name_cache = {}
_coname_cache = {}
_code_has_self = {}
_obj_tuple_cache = {}


def _scan_var_name(code, call_index):
    co_code = code.co_code
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
    key = (frame.f_code, frame.f_lasti)
    vn = _var_name_cache.get(key, _MISSING)
    if vn is _MISSING:
        vn = _var_name_cache[key] = _scan_var_name(key[0], key[1])
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
        if varname is None:
            key = (code, frame.f_lasti)
            varname = _clean_var_name_cache.get(key, _MISSING)
            if varname is _MISSING:
                raw_vn = _var_name_cache.get(key, _MISSING)
                if raw_vn is _MISSING:
                    raw_vn = _var_name_cache[key] = _scan_var_name(code, key[1])
                varname = remove_underscore(raw_vn) if raw_vn is not None else None
                _clean_var_name_cache[key] = varname
            if varname is not None:
                l.append((varname, name_to_idx[varname]))
                name_to_idx[varname] += 1
        else:
            varname = remove_underscore(varname)
            l.append((varname, name_to_idx[varname]))
            name_to_idx[varname] += 1

        has_self = _code_has_self.get(code)
        if has_self is None:
            has_self = _code_has_self[code] = _check_code_has_self(code)

        if has_self:
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
            coname = _coname_cache.get(code)
            if coname is None:
                coname = code.co_name
                if coname == "<module>":
                    modules = frame.f_globals["__name__"]
                    coname = modules.rsplit(".", 1)[-1]
                    coname = remove_underscore(coname)
                else:
                    coname = remove_underscore(coname)
                    _coname_cache[code] = coname
            l.append((coname, name_to_idx[coname]))
            name_to_idx[coname] += 1

        varname = None
        frame = frame.f_back
    l.reverse()
    return l

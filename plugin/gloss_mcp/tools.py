import itertools
import json
import threading
import weakref

from binaryninja import InstructionTextTokenType, SymbolBinding, SymbolType, execute_on_main_thread_and_wait
from binaryninjaui import UIContext

TOOLS = {}

_views = weakref.WeakValueDictionary()  # ordinal -> BinaryView
_ordinal_seq = itertools.count(1)
_views_lock = threading.Lock()
_MAX_RESULTS = 100


def _paginated(header, rows, full):
    """Build a header+rows response, truncating if not full."""
    total = len(rows)
    if not full:
        rows = rows[:_MAX_RESULTS]
    out = {"header": header, "rows": rows}
    if len(rows) < total:
        out["truncated"] = total
    return json.dumps(out)


def tool(params=None, optional=None):
    def decorator(fn):
        properties = params or {}
        opt = set(optional or [])
        TOOLS[fn.__name__] = {
            "description": (fn.__doc__ or fn.__name__).strip(),
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": [k for k in properties if k not in opt],
            },
            "handler": fn,
        }
        return fn

    return decorator


def _refresh_views():
    """Sync the view registry with the UI."""
    incoming = []

    def _collect():
        for ctx in UIContext.allContexts():
            for tab in ctx.getTabs():
                for vf in ctx.getAllViewFramesForTab(tab):
                    bv = vf.getCurrentBinaryView()
                    if bv is not None:
                        incoming.append(bv)

    execute_on_main_thread_and_wait(_collect)

    # Suppress Raw views when an analyzed view exists for the same file.
    has_analyzed = {bv.file.filename for bv in incoming if bv.view_type != "Raw"}
    incoming = [
        bv
        for bv in incoming
        if bv.view_type != "Raw" or bv.file.filename not in has_analyzed
    ]

    with _views_lock:
        known = {bv.file.session_id: ordinal for ordinal, bv in _views.items()}

        for bv in incoming:
            sid = bv.file.session_id
            if sid not in known:
                ordinal = next(_ordinal_seq)
                _views[ordinal] = bv
                known[sid] = ordinal


def require_bv(session):
    ordinal = session.bv_ordinal
    if ordinal is None:
        raise ValueError("No binary selected. Call select_binary first.")
    bv = _views.get(ordinal)
    if bv is None:
        session.bv_ordinal = None
        raise ValueError("Binary view is no longer valid.")
    return bv


def _resolve_address(bv, address):
    """Resolve an address expression. Returns int."""
    try:
        return bv.parse_expression(address)
    except ValueError:
        raise ValueError(f"Cannot resolve address: {address!r}")


def _resolve_function(bv, identifier):
    """Resolve a function by name or address expression. Returns Function or raises."""
    funcs = bv.get_functions_by_name(identifier)
    if funcs:
        return funcs[0]

    try:
        addr = bv.parse_expression(identifier)
    except ValueError:
        raise ValueError(f"Cannot find function: {identifier!r}")

    func = bv.get_function_at(addr)
    if func is not None:
        return func
    raise ValueError(f"No function at 0x{addr:x}")


def _func_header(func):
    """Return ['; name @ 0xaddr', '; type'] lines."""
    return [f"; {func.symbol.full_name} @ 0x{func.start:x}", f"; {func.type}"]


def _bb_in_range(bb_start, bb_end, start, end):
    """Check if a basic block [bb_start, bb_end) overlaps [start, end)."""
    if start is not None and bb_end <= start:
        return False
    if end is not None and bb_start >= end:
        return False
    return True


def _format_disasm(bv, func, start=None, end=None):
    """Format native disassembly: address, raw bytes, instruction text with binja annotations.

    Binja's disassembly_text already includes case labels and noreturn annotations as
    standalone lines (no InstructionToken). Those are emitted as-is without a bytes column.
    """
    lines = _func_header(func)

    for bb in func.basic_blocks:
        if not _bb_in_range(bb.start, bb.end, start, end):
            continue
        lines.append("")
        is_loop = any(e.back_edge for e in bb.incoming_edges)
        for dl in bb.disassembly_text:
            text = str(dl)
            if not text.strip():
                continue

            has_insn = any(
                t.type == InstructionTextTokenType.InstructionToken for t in dl.tokens
            )
            if not has_insn:
                # Annotation-only line (case label, noreturn, etc.)
                lines.append(f"  {text}")
                continue

            length = bv.get_instruction_length(dl.address)
            raw = bv.read(dl.address, length)
            hexbytes = raw.hex()

            suffix = ""
            if is_loop:
                suffix = "  ; loop"
                is_loop = False

            lines.append(f"0x{dl.address:x}  {hexbytes:<22s} {text}{suffix}")

    return "\n".join(lines)


def _format_hlil(func):
    """Format HLIL for a function: rendered decompiler lines with address prefix and global annotations."""
    hlil = func.hlil
    if hlil is None:
        return "(no HLIL available)"

    lines = _func_header(func)

    for dl in hlil.root.lines:
        text = str(dl)

        annotations = []
        for tok in dl.tokens:
            if tok.type == InstructionTextTokenType.DataSymbolToken:
                annotations.append(f"{tok.text}=0x{tok.value:x}")

        suffix = f"  ; {', '.join(annotations)}" if annotations else ""
        addr = f"0x{dl.address:x}" if text.strip() else ""
        lines.append(f"{addr}  {text}{suffix}" if addr else "")

    return "\n".join(lines)


def _format_il(func, il_obj, start=None, end=None):
    """Format an IL (LLIL/MLIL) function: disassembly_text lines with address prefix, annotations, loop markers."""
    lines = _func_header(func)

    filtering = start is not None or end is not None
    for bb in il_obj.basic_blocks:
        if filtering:
            src = bb.source_block
            if src is None or not _bb_in_range(src.start, src.end, start, end):
                continue
        lines.append("")
        is_loop = any(e.back_edge for e in bb.incoming_edges)
        bb_head = True
        for dl in bb.disassembly_text:
            text = str(dl)
            if not text.strip():
                continue

            annotations = []
            if bb_head:
                bb_head = False
                for ann_toks in func.get_block_annotations(dl.address, func.arch):
                    annotations.append("".join(t.text for t in ann_toks))
            if is_loop:
                annotations.append("loop")
                is_loop = False
            for tok in dl.tokens:
                if tok.type == InstructionTextTokenType.DataSymbolToken:
                    annotations.append(f"{tok.text}=0x{tok.value:x}")

            suffix = f"  ; {', '.join(annotations)}" if annotations else ""
            lines.append(f"0x{dl.address:x}  {text}{suffix}")

    return "\n".join(lines)


def _format_mlil(func, start=None, end=None):
    """Format MLIL for a function."""
    mlil = func.mlil
    if mlil is None:
        return "(no MLIL available)"
    return _format_il(func, mlil, start, end)


def _format_llil(func, start=None, end=None):
    """Format LLIL for a function."""
    llil = func.llil
    if llil is None:
        return "(no LLIL available)"
    return _format_il(func, llil, start, end)


# --- Session ---


@tool()
def list_binaries(session):
    """List open binaries."""
    _refresh_views()
    result = []
    for ordinal in sorted(_views):
        bv = _views.get(ordinal)
        if bv is None:
            continue
        result.append(
            {
                "ordinal": ordinal,
                "filename": bv.file.filename,
                "view_type": bv.view_type,
            }
        )
    return json.dumps(result)


@tool({"ordinal": {"type": "integer", "description": "Ordinal from list_binaries"}})
def select_binary(session, ordinal):
    """Select a binary for this session."""
    _refresh_views()
    bv = _views.get(ordinal)
    if bv is None:
        raise ValueError(f"Unknown ordinal {ordinal}")
    session.bv_ordinal = ordinal
    return json.dumps(
        {
            "ordinal": ordinal,
            "filename": bv.file.filename,
            "view_type": bv.view_type,
        }
    )


@tool({"full": {"type": "boolean"}}, optional=["full"])
def binary_info(session, full=False):
    """Arch, platform, entry point, segments, sections."""
    bv = require_bv(session)
    limit = None if full else _MAX_RESULTS

    all_segments = []
    for seg in bv.segments:
        perm = ("r" if seg.readable else "") + ("w" if seg.writable else "") + ("x" if seg.executable else "")
        all_segments.append([f"0x{seg.start:x}", f"0x{seg.end:x}", perm])

    all_sections = []
    for name, sec in bv.sections.items():
        sem = sec.semantics.name.replace("SectionSemantics", "")
        all_sections.append([name, f"0x{sec.start:x}", f"0x{sec.end:x}", sem])

    segments = all_segments[:limit] if limit else all_segments
    sections = all_sections[:limit] if limit else all_sections

    out = {
        "filename": bv.file.filename,
        "view_type": bv.view_type,
        "arch": bv.arch.name if bv.arch else None,
        "platform": bv.platform.name if bv.platform else None,
        "address_size": bv.address_size,
        "endianness": bv.endianness.name,
        "entry_point": f"0x{bv.entry_point:x}",
        "segments": {"header": ["start", "end", "perm"], "rows": segments},
        "sections": {"header": ["name", "start", "end", "semantics"], "rows": sections},
    }
    truncated = {}
    if len(segments) < len(all_segments):
        truncated["segments"] = len(all_segments)
    if len(sections) < len(all_sections):
        truncated["sections"] = len(all_sections)
    if truncated:
        out["truncated"] = truncated
    return json.dumps(out)


# --- Navigation ---


@tool(
    {"match": {"type": "string"}, "full": {"type": "boolean"}},
    optional=["match", "full"],
)
def list_functions(session, match=None, full=False):
    """List functions."""
    bv = require_bv(session)
    results = []
    needle = match.lower() if match else None
    for func in bv.functions:
        name = func.symbol.full_name
        if needle is not None and needle not in name.lower() and needle not in func.name.lower():
            continue
        results.append([f"0x{func.start:x}", name])
    return _paginated(["address", "name"], results, full)


@tool(
    {"address": {"type": "string", "description": "Address expression"}, "full": {"type": "boolean"}},
    optional=["full"],
)
def get_xrefs(session, address, full=False):
    """Cross-references to an address."""
    bv = require_bv(session)
    addr = _resolve_address(bv, address)

    code_refs = []
    for ref in bv.get_code_refs(addr):
        fn_name = ref.function.symbol.full_name if ref.function else None
        code_refs.append([f"0x{ref.address:x}", fn_name])

    data_refs = []
    for ref_addr in bv.get_data_refs(addr):
        fn_name = None
        funcs = bv.get_functions_containing(ref_addr)
        if funcs:
            fn_name = funcs[0].symbol.full_name
        data_refs.append([f"0x{ref_addr:x}", fn_name])

    total_code = len(code_refs)
    total_data = len(data_refs)
    if not full:
        code_refs = code_refs[:_MAX_RESULTS]
        data_refs = data_refs[:_MAX_RESULTS]

    out = {
        "target": f"0x{addr:x}",
        "header": ["address", "function"],
        "code_refs": code_refs,
        "data_refs": data_refs,
    }
    truncated = {}
    if len(code_refs) < total_code:
        truncated["code_refs"] = total_code
    if len(data_refs) < total_data:
        truncated["data_refs"] = total_data
    if truncated:
        out["truncated"] = truncated
    return json.dumps(out)


@tool(
    {"address": {"type": "string", "description": "Address expression"}},
)
def function_at(session, address):
    """Resolve address to containing function(s)."""
    bv = require_bv(session)
    addr = _resolve_address(bv, address)
    funcs = bv.get_functions_containing(addr)
    if not funcs:
        raise ValueError(f"No function contains 0x{addr:x}")
    results = []
    for func in funcs:
        results.append({
            "name": func.symbol.full_name,
            "start": f"0x{func.start:x}",
            "offset": f"+0x{addr - func.start:x}",
        })
    return json.dumps({"address": f"0x{addr:x}", "functions": results})


# --- Code ---


@tool(
    {
        "function": {
            "type": "string",
            "description": "Function name or address expression",
        },
        "start": {
            "type": "string",
            "description": "Start address expression",
        },
        "end": {
            "type": "string",
            "description": "End address expression (exclusive)",
        },
    },
    optional=["start", "end"],
)
def get_disasm(session, function, start=None, end=None):
    """Native disassembly for a function. Optional address range rounds to basic block boundaries."""
    bv = require_bv(session)
    func = _resolve_function(bv, function)
    s = _resolve_address(bv, start) if start else None
    e = _resolve_address(bv, end) if end else None
    return _format_disasm(bv, func, s, e)


@tool(
    {
        "function": {
            "type": "string",
            "description": "Function name or address expression",
        },
        "il": {
            "type": "string",
            "enum": ["llil", "mlil"],
        },
        "start": {
            "type": "string",
            "description": "Start address expression",
        },
        "end": {
            "type": "string",
            "description": "End address expression (exclusive)",
        },
    },
    optional=["start", "end"],
)
def get_il(session, function, il, start=None, end=None):
    """LLIL or MLIL for a function. Optional address range rounds to basic block boundaries."""
    bv = require_bv(session)
    func = _resolve_function(bv, function)
    s = _resolve_address(bv, start) if start else None
    e = _resolve_address(bv, end) if end else None

    if il == "llil":
        return _format_llil(func, s, e)
    elif il == "mlil":
        return _format_mlil(func, s, e)
    else:
        raise ValueError(f"IL level {il!r} not supported")


@tool(
    {
        "function": {
            "type": "string",
            "description": "Function name or address expression",
        },
    },
)
def decompile(session, function):
    """Decompiled code (HLIL) for a function."""
    bv = require_bv(session)
    func = _resolve_function(bv, function)
    return _format_hlil(func)


# --- Data ---


@tool(
    {"match": {"type": "string"}, "full": {"type": "boolean"}},
    optional=["match", "full"],
)
def list_data_vars(session, match=None, full=False):
    """List data variables."""
    bv = require_bv(session)
    results = []
    needle = match.lower() if match else None
    for addr, var in bv.data_vars.items():
        sym = bv.get_symbol_at(addr)
        name = sym.full_name if sym else None
        typ = str(var.type)
        if needle is not None:
            raw_name = sym.name if sym else ""
            if needle not in (name or "").lower() and needle not in raw_name.lower() and needle not in typ.lower():
                continue
        results.append([f"0x{addr:x}", name, typ])
    return _paginated(["address", "name", "type"], results, full)


@tool(
    {"pattern": {"type": "string", "description": "Hex bytes, ? wildcards (e.g. '55 4? ?? e5')"}},
)
def search_bytes(session, pattern):
    """Search for a byte pattern. Hard cap at 100 results."""
    bv = require_bv(session)
    results = []
    for addr, match in bv.search(pattern, limit=_MAX_RESULTS):
        results.append(f"0x{addr:x}")
    return json.dumps({"addresses": results})


_MAX_READ = 4096
_READ_DEFAULT = 256


@tool(
    {
        "address": {
            "type": "string",
            "description": "Address expression",
        },
        "length": {
            "type": "integer",
            "description": f"Byte count (default {_READ_DEFAULT}, max {_MAX_READ})",
        },
    },
    optional=["length"],
)
def read_memory(session, address, length=_READ_DEFAULT):
    """Read raw bytes at an address."""
    bv = require_bv(session)
    addr = _resolve_address(bv, address)
    length = min(max(1, length), _MAX_READ)
    data = bv.read(addr, length)
    if not data:
        raise ValueError(f"No readable data at 0x{addr:x}")

    lines = []
    for i in range(0, len(data), 32):
        chunk = data[i : i + 32]
        lines.append(f"0x{addr + i:x}: {chunk.hex()}")
    return "\n".join(lines)


@tool(
    {
        "match": {"type": "string"},
        "full": {"type": "boolean"},
    },
    optional=["match", "full"],
)
def list_strings(session, match=None, full=False):
    """List strings."""
    bv = require_bv(session)
    results = []
    needle = match.lower() if match else None
    for s in bv.strings:
        value = s.value
        if needle is not None and needle not in value.lower():
            continue
        results.append([f"0x{s.start:x}", value])
    return _paginated(["address", "value"], results, full)


@tool(
    {"match": {"type": "string"}, "full": {"type": "boolean"}},
    optional=["match", "full"],
)
def list_imports(session, match=None, full=False):
    """List imported symbols."""
    bv = require_bv(session)
    results = []
    needle = match.lower() if match else None
    for sym in bv.get_symbols_of_type(SymbolType.ImportAddressSymbol):
        name = sym.full_name
        ns = str(sym.namespace)
        module = ns if ns != "BNINTERNALNAMESPACE" else None
        if needle is not None:
            if needle not in name.lower() and needle not in sym.name.lower() and (
                module is None or needle not in module.lower()
            ):
                continue
        results.append([f"0x{sym.address:x}", name, module])
    return _paginated(["address", "name", "module"], results, full)


@tool(
    {"match": {"type": "string"}, "full": {"type": "boolean"}},
    optional=["match", "full"],
)
def list_exports(session, match=None, full=False):
    """List exported symbols."""
    bv = require_bv(session)
    results = []
    needle = match.lower() if match else None
    for sym_type in (SymbolType.FunctionSymbol, SymbolType.DataSymbol):
        for sym in bv.get_symbols_of_type(sym_type):
            if sym.binding != SymbolBinding.GlobalBinding:
                continue
            name = sym.full_name
            if needle is not None and needle not in name.lower() and needle not in sym.name.lower():
                continue
            kind = "func" if sym_type == SymbolType.FunctionSymbol else "data"
            results.append([f"0x{sym.address:x}", name, kind])
    return _paginated(["address", "name", "type"], results, full)

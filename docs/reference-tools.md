# Reference Plugin Tool Inventory

Catalog of MCP tools from two Binary Ninja reference plugins. Notes on what
Binary Ninja API they actually call, parameter signatures, return formats,
and implementation quirks.

**Sources:**
- **A** = [BinAssistMCP](https://github.com/jtang613/BinAssistMCP) — FastMCP + hypercorn, pydantic models
- **F** = [binary_ninja_mcp](https://github.com/fosdickio/binary_ninja_mcp) — stdlib HTTP bridge, zero plugin deps

Both use `str(il_instruction)` for IL serialization. Neither does structured
AST output. Both have pagination that materializes the full list then slices.

---

## Binary / Session Management

### list_binaries
**A + F.** Enumerate open BinaryViews.

| | A | F |
|---|---|---|
| Params | none | none |
| BN API | `context_manager.sync_with_binja()` (internal) | Iterates `self._views_by_id` weak refs, `vb.file.filename` |
| Returns | `{binaries: [names], sync_status: {added, removed, unchanged}}` | Multi-line text: ordinal, basename, view_id, active flag, path |

### get_binary_status
**A + F.** Load status of the binary.

| | A | F |
|---|---|---|
| Params | `filename: str` | none |
| BN API | internal context manager | `bv.file.filename` |
| Returns | `{name, loaded, file_path, analysis_complete, load_time}` | `"loaded=True filename=/path"` |

### select_binary (F only)
Switch which BinaryView is active for subsequent tool calls.

- **Params:** `view: str` — ordinal, view id, full path, or basename
- **BN API:** Matches against internal view registry, sets `self.current_view`
- **Returns:** Text with selected binary info

### list_platforms (F only)
List all registered Binary Ninja platform names.

- **Params:** none
- **BN API:** `list(bn.Platform)`, `getattr(p, 'name', str(p))`
- **Returns:** Newline-joined platform names

---

## Functions — Listing & Search

### list_methods / get_functions
**A + F.** List all functions, paginated.

| | A (`get_functions`) | F (`list_methods`) |
|---|---|---|
| Params | `filename: str` | `offset: int = 0`, `limit: int = 100` |
| BN API | `bv.functions` — reads `func.symbol.type`, `func.return_type`, `func.parameter_vars`, `func.basic_blocks` | `bv.functions` — reads `func.start`, `func.name`, `func.raw_name` |
| Returns | `[{name, address, size, symbol_type, parameter_count, return_type, basic_block_count}]` | Lines of function names |

### search_functions_by_name
**A + F.** Case-insensitive substring match on function names.

| | A | F |
|---|---|---|
| Params | `filename, search_term` | `query, offset=0, limit=100` |
| BN API | `bv.functions`, `search_term.lower() in func.name.lower()` | Same pattern |
| Returns | `[{name, address, symbol_type}]` sorted alpha | Text lines with name, address, raw_name, symbol type |

### get_functions_advanced (A only)
Filter/sort functions by size, params, complexity.

- **Params:** `filename, name_filter="", min_size=0, max_size=0, has_parameters=False, sort_by="address", limit=0`
- **sort_by:** `"address"`, `"name"`, `"size"`, `"complexity"`
- **BN API:** `bv.functions`, `func.total_bytes`, `func.parameter_vars`, `func.basic_blocks`, `func.call_sites`, `func.callers`, `func.return_type`
- **Returns:** `[{name, address, size, parameter_count, basic_block_count, complexity, call_count, caller_count, return_type}]`
- **Notes:** Cyclomatic complexity = edges - nodes + 2

### search_functions_advanced (A only)
Search across names, comments, callees, variables.

- **Params:** `filename, search_term, search_in="name", case_sensitive=False`
- **search_in:** `"name"`, `"comment"`, `"calls"`, `"variables"`, `"all"`
- **BN API:** `func.comment`, `func.call_sites`, `bv.get_function_at()`, `func.vars`
- **Returns:** `[{name, address, size, match_reason: [...], comment}]`

### get_function_statistics (A only)
Aggregate stats over all functions.

- **Params:** `filename`
- **Returns:** `{total_functions, size_statistics, complexity_statistics, parameter_statistics, basic_block_statistics, top_largest_functions, top_most_complex_functions}`

### get_entry_points (F only)
List binary entry points.

- **Params:** none
- **BN API:** `bv.entry_point`, tries well-known names (`_start`, `entry`, `WinMain`, `mainCRTStartup`) via `bv.get_symbol_by_name()`
- **Returns:** Tab-separated `"0xADDR\tname"` lines

### function_at (F only)
Resolve address to function name(s).

- **Params:** `address: str`
- **BN API:** `bv.get_functions_containing(address)`
- **Returns:** List of function names

### make_function_at (F only)
Create a function at an address.

- **Params:** `address: str`, `platform: str = ""`
- **BN API:** `bv.get_function_at(addr)` (existence check), `bn.Platform[arch]` or `bv.platform`, `bv.create_user_function(addr, plat)` or `bv.add_function(addr, plat)`
- **Returns:** Created function name, or "already exists"
- **Notes:** On unknown platform, returns full platform list + fuzzy suggestions

---

## Decompilation & IL

### decompile_function / get_code
**A + F.** Get decompiled or IL output for a function.

| | A (`get_code`) | F (`decompile_function`) |
|---|---|---|
| Params | `filename, function_name_or_address, format="decompile"` | `name: str` |
| Formats | `decompile`, `hlil`, `mlil`, `llil`, `disasm`, `pseudo_c` | HLIL only (with MLIL fallback) |
| BN API | `func.hlil` / `func.mlil` / `func.llil` blocks, `str(instr)` per instruction; `bv.get_disassembly(addr)` for disasm | `func.analysis_skipped = False`, `bv.update_analysis_and_wait()`, `func.hlil.instructions` → `str(ins)`, fallback to `func.mlil.instructions` |
| Returns | `{function, address, format, code: str}` | Lines of `"ADDR        instruction_text"` |

**Neither uses the proper decompiler C output.** Both stringify HLIL instructions. BinAssistMCP's `pseudo_c` mode builds a signature + HLIL body, not LinearViewObject output. The correct API for C output is `bn.LinearViewObject.language_representation()` with `DisassemblyOption.WaitForIL`.

### get_il (F only)
Get IL in a specific view with optional SSA form.

- **Params:** `name_or_address: str`, `view: str = "hlil"`, `ssa: bool = False`
- **BN API:** Selects `func.hlil` / `func.mlil` / `func.llil`, then `.ssa_form` if `ssa=True`, iterates `.instructions`, `str()` each
- **Returns:** Lines of `"ADDR        text"`

### fetch_disassembly
**A (via get_code format=disasm) + F.** Raw assembly.

- **Params (F):** `name: str`
- **BN API:** `func.basic_blocks`, `bv.get_disassembly(addr)` per instruction in each block
- **Returns:** Assembly text with address annotations

### get_basic_blocks (A only)
CFG basic block list for a function.

- **Params:** `filename, function_name_or_address`
- **BN API:** `func.basic_blocks`, `block.outgoing_edges`, `block.incoming_edges`, `edge.target.start`, `str(edge.type)`
- **Returns:** `[{start, end, length, instruction_count, successors: [{address, type}], predecessors: [{address}]}]`

### analyze_function (A only)
Comprehensive function analysis.

- **Params:** `filename, function_name_or_address`
- **BN API:** `func.basic_blocks`, `func.call_sites`, `func.callers`, `func.parameter_vars`, `func.vars`, `func.return_type`
- **Returns:** `{name, address, size, basic_block_count, instruction_count, parameter_count, local_variable_count, complexity: {cyclomatic, call_depth}, control_flow: {entry_point, exit_points, branch_count, loop_count}, calls: {outgoing, incoming, external_calls}, types: {return_type, parameters}}`

---

## Symbols & Renaming

### rename_function / rename_symbol
**A + F.** Rename a function.

| | A (`rename_symbol`) | F (`rename_function`) |
|---|---|---|
| Params | `filename, address_or_name, new_name` | `old_name, new_name` |
| BN API | `func.name = new_name` or `bv.define_user_symbol(Symbol(DataSymbol, addr, new_name))` for data vars | `func.name = new_name`, fallback `bv.define_user_symbol(Symbol(...))`, fallback `bv.update_function(func)` |
| Notes | `_resolve_symbol()` tries hex, decimal, func name, data var, `bv.get_symbol_by_raw_name()` | **Auto-prepends `mcp_` prefix** (from `bv.Settings().get_string("mcp.renamePrefix")`) |

### rename_data (F only)
Rename a data label at an address.

- **Params:** `address: str`, `new_name: str`
- **BN API:** `bv.is_valid_offset(address)`, `bv.define_user_symbol(Symbol(DataSymbol, address, new_name))`

### batch_rename / rename_multi_variables
**A + F.** Bulk rename operations.

| | A (`batch_rename`) | F (`rename_multi_variables`) |
|---|---|---|
| Params | `filename, renames: [{address_or_name, new_name}]` | `function_identifier, mapping_json="", pairs="", renames_json=""` |
| Scope | Functions and data vars (symbol-level) | Local variables within one function |
| BN API | Delegates to `rename_symbol()` per item | `func.get_variable_by_name(old)`, `var.name = new`, fallback `func.create_user_var()`, then `func.reanalyze()` |
| Notes | Per-item errors don't abort batch | Accepts multiple input formats: JSON object, JSON array of `{old,new}`, comma-separated pairs. Alias keys: `from/to`, `src/dst`, `before/after` |

---

## Variables & Stack

### variables_tool (A only)
Unified variable management.

- **Params:** `filename, action, function_name_or_address, var_name="", var_type="", new_name="", storage="auto"`
- **Actions:**
  - `list`: `func.parameter_vars` + `func.vars` → `[{name, type, category, storage, identifier}]`
  - `create`: `bv.parse_type_string(var_type)`, `func.create_user_var(var, type, name)`
  - `rename`: finds var in `func.vars`, sets `.name`
  - `set_type`: `bv.parse_type_string()`, `func.create_user_var(var, type, name)`

### rename_single_variable (F only)
- **Params:** `function_name, variable_name, new_name`
- **BN API:** `func.get_variable_by_name(name)`, `variable.name = new_name`

### retype_variable (F only)
- **Params:** `function_name, variable_name, type_str`
- **BN API:** `func.get_variable_by_name(name)`, `variable.type = type_str`

### set_local_variable_type (F only)
- **Params:** `function_address, variable_name, new_type`
- **BN API:** `func.get_variable_by_name()`, `bv.parse_type_string(new_type)`, `var.type = t`, fallback `func.create_user_var(var, t, name)`, `func.reanalyze(UserFunctionUpdate)`

### get_stack_frame_vars / get_function_stack_layout
**A + F.** Stack frame layout for a function.

| | A (`get_function_stack_layout`) | F (`get_stack_frame_vars`) |
|---|---|---|
| Params | `filename, function_name_or_address` | `function_identifier` |
| BN API | `func.stack_layout`, `func.stack_adjustment` | `func.stack_layout` or `func.vars`; `var.name`, `var.storage`, `var.type.width` |
| Returns | `{function, address, stack_variables: [{name, offset, type}], total_local_size}` | `[{addr, vars: [{name, offset, size, type}]}]` |

---

## Types

### types_tool (A only)
Unified type CRUD.

- **Params:** `filename, action, name="", definition="", size=0, members=None, base_type="", class_name="", member_name="", member_type="", offset=0`
- **Actions:**
  - `list`: Paginated, categorized (struct/enum/array/pointer/function/primitive) from `bv.types.items()`
  - `info`: `bv.types[name]` → struct members `[{name, type, offset, size}]`, enum members `[{name, value}]`, array `{element_type, count}`, pointer `{target_type}`, function `{return_type, parameters}`
  - `create`: `bv.parse_type_string(definition)`, `bv.define_user_type(name, type)`
  - `create_class`: `StructureBuilder.create()`, `struct.width = size`, `bv.define_user_type()`
  - `create_enum`: `EnumerationBuilder.create()`, append members, `Type.enumeration_type(arch, builder, 4)` — **hardcoded 4-byte enum**
  - `create_typedef`: `Type.named_type_from_type(name, parsed)`, `bv.define_user_type()`
  - `add_member`: `bv.types[class_name]`, `mutable_copy()`, `struct_builder.insert(offset, type, name)`, `bv.define_user_type()`

### list_local_types (F only)
- **Params:** `offset=0, count=200, include_libraries=False`
- **BN API:** `bv.user_type_container.types`, `bv.types`, optionally `bv.platform.type_libraries[i].named_types`
- **Returns:** `[{name, kind, type_class, decl}]` deduplicated by `(name, decl)`

### search_types (F only)
- **Params:** `query, offset=0, count=200, include_libraries=False`
- **BN API:** Calls `list_local_types(0, 1_000_000, ...)`, then case-insensitive substring filter on `name` and `decl`

### get_type_info / get_user_defined_type (F only)
Two tools, slightly different scope.

| | `get_type_info` | `get_user_defined_type` |
|---|---|---|
| Params | `type_name` | `type_name` |
| BN API | `bv.get_type_by_name()`, fallback `bv.platform.type_libraries[i].get_type_by_name()` | `bv.user_type_container.types` iteration |
| Returns | `{name, kind, decl, members, enum_members, source}` | `{name, type, definition}` (C-style declaration) |
| Notes | Checks library types too | User-defined only |

### define_types / declare_c_type (F only)
Functionally identical — parse C and define types.

| | `define_types` | `declare_c_type` |
|---|---|---|
| Params | `c_code: str` | `c_declaration: str` |
| BN API | `bv.parse_types_from_string()`, `bv.define_user_type()` per result | Same |
| Returns | `"Defined types: ..."` | `"Declared types (N): ..."` |

### set_function_prototype (F only)
- **Params:** `name_or_address, prototype`
- **BN API:** Strips trailing `;`, tries `bv.parse_type_string(proto)`, fallback `bv.parse_types_from_string()`, fallback regex insert function name + retry. `func.type = t`, `func.reanalyze(UserFunctionUpdate)`
- **Returns:** `"Applied prototype at ADDR: type_string"`

### get_classes (A only)
- **Params:** `filename`
- **BN API:** `bv.types.items()`, filters for `StructureType` instances
- **Returns:** `[{name, type: "struct", size, members: [{name, type, offset}], member_count}]`

### list_classes (F only)
- **Params:** `offset=0, limit=100`
- **BN API:** `bv.types.values()` — very broad filter, returns essentially all types
- **Returns:** Sorted name strings

---

## Cross-References

### xrefs_tool (A only)
Unified xref + call graph.

- **Params:** `filename, address_or_name, direction="both", include_calls=True`
- **BN API:**
  - Refs to: `bv.get_code_refs(addr)`
  - Refs from: `bv.get_code_refs_from(addr)` per instruction in each basic block
  - Call graph: `func.callees`, `bv.get_code_refs(func.start)` for callers
- **Returns:** `{target, direction, references_to: [{address, function}], references_from: [{from_address, to_address, to_function}], call_graph?: {function, address, callers, callees}}`

### get_xrefs_to (F only)
Code + data xrefs to an address.

- **Params:** `address: str`
- **BN API:** `bv.get_code_refs(addr)`, `bv.get_data_refs(addr)`
- **Returns:** `{address, code_references: [{function, address}], data_references: [...]}`
- **Notes:** Heuristic: looks at following call instructions (~20 bytes) to identify what callee receives the address as argument, annotates with `likely_call_context`

### get_xrefs_to_field (F only)
Xrefs to a struct member.

- **Params:** `struct_name, field_name`
- **BN API:** `bv.get_type_by_name(struct_name)`, finds field offset in `.members`, scans HLIL `str(ins)` for member access patterns
- **Notes:** String-matching on HLIL text, not structured

### get_xrefs_to_struct / get_xrefs_to_type / get_xrefs_to_enum / get_xrefs_to_union (F only)
Type-level xref scanning. All follow the same pattern:

- **BN API:** `bv.get_type_by_name()`, find global data vars of that type, `bv.get_code_refs(var_addr)`, scan HLIL for string mentions
- `get_xrefs_to_type` additionally scans function signatures via `str(func.type)`
- `get_xrefs_to_enum` scans HLIL for numeric constant values of enum members
- **Notes:** All of these are brute-force HLIL string scans

---

## Comments

### set_comment
**A (via comments_tool) + F.**

| | A | F |
|---|---|---|
| Params | `filename, action="set", address, text` | `address, comment` |
| BN API | `func.set_comment_at(addr, comment)` if in function, fallback `bv.set_comment_at(addr, comment)` | `bv.set_comment_at(address, comment)` |

### get_comment
**A (via comments_tool) + F.**

| | A | F |
|---|---|---|
| Params | `filename, action="get", address` | `address` |
| BN API | `func.get_comment_at(addr)` first, fallback `bv.get_comment_at(addr)` | `bv.get_comment_at(address)` |

### list_comments (A only, via comments_tool action="list")
- **BN API:** Collects `func.comment` (function-level), `func.comments` dict (instruction-level), `bv.address_comments` dict (BV-level)

### delete_comment (F only)
- **Params:** `address: str`
- **BN API:** `bv.set_comment_at(address, None)`

### set_function_comment
**A (via comments_tool action="set_function") + F.**

| | A | F |
|---|---|---|
| BN API | `func.comment = text` | `bv.set_comment_at(func.start, comment)` — **uses address comment, not func.comment** |

### get_function_comment (F only)
- **BN API:** `bv.get_comment_at(func.start)` — matches the set, but not `func.comment`

### delete_function_comment (F only)
- **BN API:** `func.comment = None` — **inconsistent with set, which uses `bv.set_comment_at`**

---

## Data & Memory

### get_data_vars / list_data_items
**A + F.** List all defined data variables.

| | A (`get_data_vars`) | F (`list_data_items`) |
|---|---|---|
| Params | `filename` | `offset=0, limit=100` |
| BN API | `bv.data_vars.items()`, `bv.get_symbol_at(addr)` | `bv.data_vars`, `bv.get_data_var_at(var)`, `bv.read_int(var, width)`, `bv.get_symbol_at(var)` |
| Returns | `[{address, type, size, name}]` sorted by addr | `[{address, name, raw_name, type, size, width, value, bytes_hex, ascii_preview}]` |

### get_data_at_address / hexdump_address
**A + F.** Read memory at an address.

| | A (`get_data_at_address`) | F (`hexdump_address`) |
|---|---|---|
| Params | `filename, address, size=None` | `address, length=-1` |
| BN API | `bv.read(addr, size)` | If `length < 0`: `infer_data_size(addr)` (type width or HLIL heuristic, fallback 64). `bv.read(addr, length)`, `bv.get_symbol_at(addr)` |
| Returns | `{address, size, raw_hex, as_uint32, as_int32, as_uint64, as_int64, as_string, defined_type, symbol_name}` | 16-bytes-per-line hexdump with address | hex | ASCII columns |

### hexdump_data (F only)
Hexdump by name or address.

- **Params:** `name_or_address, length=-1`
- **BN API:** `_resolve_name_to_address()` tries `bv.get_symbol_by_raw_name`, `bv.get_symbol_by_name`, auto-label regex, data_var scan. Then same as hexdump_address.

### get_data_decl (F only)
C declaration + hexdump for a data symbol.

- **Params:** `name_or_address, length=-1`
- **BN API:** `bv.get_data_var_at(addr)` → `dv.type`, fallback `bv.get_type_at(addr)`, `bv.read(addr, size)`
- **Returns:** `{address, name, size, type, decl, hexdump}` — for char arrays, shows C string initializer

### create_data_var (A only)
- **Params:** `filename, address, var_type, name=""`
- **BN API:** `bv.define_data_var(addr, type)`, optionally `bv.define_user_symbol()`

### search_bytes (A only)
- **Params:** `filename, pattern, start_address="", max_results=100`
- **Pattern format:** hex string `"90 90 90"` or `"909090"`
- **BN API:** `bv.find_next_data(addr, bytes)`, `bv.read(addr, size)`, `bv.get_functions_containing(addr)`
- **Returns:** `[{address, context_hex, function}]`
- **Notes:** Advances by 1 after each hit (overlapping matches possible)

### patch_bytes (F only)
Write bytes to the binary.

- **Params:** `address, data, save_to_file=True`
- **BN API:** `bv.read(addr, len)` (original), `bv.write(addr, bytes)`, optionally `bv.file.save()`. macOS: runs `codesign` subprocess.
- **Data format:** `"90 90"`, `"9090"`, `"0x90 0x90"`, or JSON array `"[0x90, 0x90]"`

---

## Strings

### get_strings / list_strings
**A + F.** Paginated string listing.

| | A (`get_strings`) | F (`list_strings`) |
|---|---|---|
| Params | `filename, page_size=100, page_number=1` | `offset=0, count=100` |
| BN API | `bv.strings` — materializes all, then slices | `bv.get_strings()` or `bv.strings`, reads `bv.read(addr, length)` and decodes |
| Returns | `{strings: [{value, address, length, type}], page_size, page_number, total_count, total_pages}` | Text lines |

### search_strings / list_strings_filter
**A + F.** Filtered string search.

| | A (`search_strings`) | F (`list_strings_filter`) |
|---|---|---|
| Params | `filename, pattern, case_sensitive=False, page_size=100, page_number=1` | `offset=0, count=100, filter=""` |
| BN API | `bv.strings`, substring match on `.value` | Fetches all strings (limit=MAX_INT), case-insensitive substring, then paginates |

### list_all_strings (F only)
Aggregates all pages into one result.

- **Params:** `batch_size=500`
- **BN API:** Repeated `/strings` calls with incrementing offset
- **Returns:** Tab-separated `"address\tlength\ttype\tvalue"` lines

---

## Segments, Sections, Imports, Exports, Namespaces

### get_segments / list_segments
**A + F.**

- **BN API:** `bv.segments` — `segment.start`, `.end`, `.readable`, `.writable`, `.executable`
- A returns `[{start, end, length, readable, writable, executable, data_offset, data_length}]`
- F returns formatted text lines

### get_sections / list_sections
**A + F.**

- **BN API:** `bv.sections.values()` — `.start`, `.end`, `.name`, `.type`, `.semantics`, `.align`
- A returns `[{name, start, end, length, type, align, entry_size}]`
- F returns `"start-end\tsize\tname[\tsemantics]"` lines

### get_imports / list_imports
**A + F.**

| | A | F |
|---|---|---|
| BN API | `bv.get_symbols_of_type(ImportedFunctionSymbol)` + `ImportedDataSymbol`, groups by `sym.namespace` | `bv.get_symbols_of_type(ImportedFunctionSymbol)` |
| Returns | Dict keyed by module → `[{name, address, type, ordinal}]` | Text lines |

### get_exports / list_exports
**A + F.**

| | A | F |
|---|---|---|
| BN API | `bv.get_symbols_of_type(FunctionSymbol)` + `DataSymbol`, filtered by `GlobalBinding` | `bv.get_symbols()`, excludes `ImportedFunctionSymbol` and `ExternalSymbol` |
| Notes | Uses binding filter — may miss non-global exports | Inclusion-by-exclusion — may include non-exports |

### get_namespaces / list_namespaces
**A + F.**

| | A | F |
|---|---|---|
| BN API | `bv.symbols.values()`, groups by `symbol.namespace` | `bv.get_symbols()`, splits names on `"::"` |
| Returns | `[{namespace, symbol_count, symbols: [{name, address, type}]}]` | Sorted unique namespace strings |

---

## Context / UI

### get_current_address (A only)
- **Params:** `filename`
- **BN API:** `bv.offset` (may not exist headless), fallback `bv.entry_points`, `bv.get_functions_containing()`, `bv.get_symbol_at()`, `bv.segments`
- **Returns:** `{address, decimal, has_current_offset, in_function?, symbol?, segment?}`

### get_current_function (A only)
- **Params:** `filename`
- **BN API:** `bv.offset`, `bv.get_functions_containing()`
- **Returns:** `{current_address, function: {name, address} or None}`

---

## Utility

### convert_number (F only)
Pure utility, no BN API calls.

- **Params:** `text: str`, `size: int = 0`
- **Accepts:** decimal, hex (`0x` or `h` suffix), binary (`0b`), octal (`0o`), char (`'A'`), string (`"ABC"`)
- **Returns:** `{bases: {hex, dec, bin, oct}, c_literal, c_string, le_bytes, be_bytes}`

### format_value (F only)
Convert + annotate a value at an address.

- **Params:** `address, text, size=0`
- **BN API:** `bv.set_comment_at(addr, annotation)`
- **Returns:** `{address, converted, applied_comment}`

---

## Analysis Control

### update_analysis_and_wait (A only)
- **Params:** `filename`
- **BN API:** `bv.update_analysis_and_wait()`

---

## Async Task Management (A only)

Internal task tracking, not Binary Ninja API.

### get_task_status
- **Params:** `task_id: str`

### cancel_task
- **Params:** `task_id: str`

### list_tasks
- **Params:** `status: str = ""` — `pending`, `running`, `completed`, `failed`, `cancelled`

---

## Implementation Patterns & Gotchas

### Symbol resolution
BinAssistMCP's `_resolve_symbol()` tries in order: hex parse → decimal parse → bounds check → function name match → data var symbol → `bv.get_symbol_by_raw_name()`. Returns None if nothing matches.

fosdickio's `get_function_by_name_or_address()` iterates `bv.functions` (name match), tries `bv.get_function_at(addr)`, tries `bv.get_symbol_by_raw_name()`.

### IL serialization
Both call `str()` on HLIL/MLIL/LLIL instructions. This is a textual serialization, not the decompiler's rendered C output. The correct API for pseudo-C is `bn.LinearViewObject.language_representation()`.

### Pagination
Both materialize the full list, then slice. No cursor-based pagination.

### fosdickio's rename prefix
`rename_function` auto-prepends a configurable prefix (default `"mcp_"`) to all new names. This is a significant UX gotcha.

### fosdickio's function comment inconsistency
`set_function_comment` writes to `bv.set_comment_at(func.start)` (address comment), but `delete_function_comment` clears `func.comment` (function-level comment). These are different comment slots.

### Error handling
- A: `@handle_exceptions` decorator, re-raises, FastMCP converts to error responses
- F: HTTP status codes from plugin side, bridge catches and returns text errors

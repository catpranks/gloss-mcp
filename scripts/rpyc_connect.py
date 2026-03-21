"""Connect to binja-headless RPyC backdoor and pull the active BinaryView.

Run this before poking at binja internals:

    exec(open("scripts/rpyc_connect.py").read())

Gives you: c (connection), bn (binaryninja module), bv (active BinaryView).
"""

import rpyc

c = rpyc.connect("localhost", 18812)
bn = c.root.binaryninja
ui = c.root.import_module("binaryninjaui")
bv = ui.UIContext.allContexts()[0].getCurrentViewFrame().getCurrentBinaryView()
print(f"bv = {bv}")

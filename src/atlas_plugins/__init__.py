"""Atlas plugins shipped with this distribution.

Each plugin is a real, entry-point-registered package (contract section 17). The
packages are intentionally **siblings, not a hierarchy**: no plugin imports
another plugin's module. The only channel between them is a typed contract id
spelled as a literal string (contract section 9).
"""

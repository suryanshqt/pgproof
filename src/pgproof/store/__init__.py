"""The artifact store: the `.pgproof` directory layout and atomic read/write.

`docs/ARCHITECTURE.md` section 7. Domain models describe artifact shapes; this
package is the only one that touches the filesystem to persist them.
"""

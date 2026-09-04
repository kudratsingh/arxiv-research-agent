"""The property tier (ADR 0069).

A package rather than a bare directory because `tests/` is itself a
package: with `__init__.py` present pytest names these modules
`tests.property.test_property_*`, so a file here can never collide with
a same-named module in `tests/`, and the tier can grow without relying
on a naming convention nobody remembers.
"""

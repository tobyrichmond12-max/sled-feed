"""Source descriptors for the SLED feed fleet.

Each source is a plain dict consumed by the reusable clearance_filter and scraper.
Adding a new skill = adding one descriptor here; the scaffolding is shared.
"""
from . import mississippi
from . import uk_contracts_finder

# attach the implementing module so the scraper can reach map_record / KNOWN_FIELDS
mississippi.SOURCE["module"] = mississippi
uk_contracts_finder.SOURCE["module"] = uk_contracts_finder

SOURCES = {
    "mississippi": mississippi.SOURCE,
    "uk_contracts_finder": uk_contracts_finder.SOURCE,
}

"""ATCs observed by the user in the automation VM's 2551Qv2018 Schedule 1.

This is a dropdown compatibility list, not a determination of a taxpayer's ATC.
Add a separate module for a different form/version instead of changing this list
to a union of codes from unrelated forms.
"""

ALLOWED_ATCS = frozenset({
    "PT 010", "PT 040", "PT 041", "PT 060", "PT 070", "PT 090",
    "PT 101", "PT 102", "PT 103", "PT 104", "PT 105", "PT 113",
    "PT 114", "PT 115", "PT 120", "PT 130", "PT 132", "PT 140",
    "PT 150", "PT 160", "PT 170", "PT 180",
})

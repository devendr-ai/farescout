"""Map ISO country codes to the destination regions used in the dashboard."""

REGION_NAMES = {
    "na": "US & Canada",
    "in": "India",
    "eu": "Europe",
    "as": "Asia",
    "me": "Middle East",
    "la": "Latin America",
    "cb": "Caribbean",
    "af": "Africa",
    "oc": "Oceania",
}

_REGIONS = {
    "na": "US CA",
    "in": "IN",
    "cb": "PR VI VG AG AI AW BB BS BQ CU CW DM DO GD GP HT JM KN KY LC MQ MS SX MF BL TC TT VC",
    "la": "MX GT BZ SV HN NI CR PA CO VE EC PE BO CL AR UY PY BR GY SR GF",
    "eu": (
        "GB IE FR ES PT IT DE NL BE LU CH AT DK NO SE FI IS PL CZ SK HU SI HR BA RS ME MK AL GR CY MT "
        "RO BG MD UA BY LT LV EE TR GE AM AZ RU MC AD SM LI XK FO GI"
    ),
    "me": "AE QA SA OM BH KW JO LB IL IQ IR SY YE PS",
    "af": (
        "EG MA DZ TN LY SD ET KE TZ UG RW ZA NA BW ZW ZM MZ MW AO NG GH CI SN CM GA CD CG MU SC MG RE "
        "CV GM GN ML BF NE TD SO DJ ER ST LR SL TG BJ MR LS SZ KM SS YT"
    ),
    "as": (
        "JP KR KP CN HK MO TW MN TH VN KH LA MM MY SG ID PH BN TL LK NP BD BT MV PK AF KZ UZ KG TJ TM"
    ),
    "oc": "AU NZ FJ PF NC PG VU WS TO CK GU MP PW FM MH KI NR TV SB",
}

COUNTRY_REGION = {cc: region for region, codes in _REGIONS.items() for cc in codes.split()}


def region_for(country_code: str | None) -> str:
    """Region key for a country, or "other" when unknown."""
    return COUNTRY_REGION.get((country_code or "").upper(), "other")

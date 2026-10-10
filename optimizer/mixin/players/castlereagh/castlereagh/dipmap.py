"""Standard Diplomacy names for webDiplomacy territories and orders.

webDip identifies territories by integer `terrID`; players (and the LLM) use three-letter
abbreviations ("PAR", "STP/NC"). The table below is the Classic map's names as the
`diplomacy` package (1.1.2) spells them, generated once from that package so the default
path no longer needs it installed. Any territory name not in the table raises KeyError,
so a new variant map fails loudly instead of rendering wrong names.
"""

POWER = {1: "ENGLAND", 2: "FRANCE", 3: "ITALY", 4: "GERMANY", 5: "AUSTRIA", 6: "TURKEY", 7: "RUSSIA"}
COUNTRY = {v: k for k, v in POWER.items()}

ABBREVIATION = {
    "Clyde": "CLY", "Edinburgh": "EDI", "Liverpool": "LVP", "Yorkshire": "YOR", "Wales": "WAL",
    "London": "LON", "Portugal": "POR", "Spain": "SPA", "North Africa": "NAF", "Tunis": "TUN",
    "Naples": "NAP", "Rome": "ROM", "Tuscany": "TUS", "Piedmont": "PIE", "Venice": "VEN",
    "Apulia": "APU", "Greece": "GRE", "Albania": "ALB", "Serbia": "SER", "Bulgaria": "BUL",
    "Rumania": "RUM", "Constantinople": "CON", "Smyrna": "SMY", "Ankara": "ANK", "Armenia": "ARM",
    "Syria": "SYR", "Sevastopol": "SEV", "Ukraine": "UKR", "Warsaw": "WAR", "Livonia": "LVN",
    "Moscow": "MOS", "St. Petersburg": "STP", "Finland": "FIN", "Sweden": "SWE", "Norway": "NWY",
    "Denmark": "DEN", "Kiel": "KIE", "Berlin": "BER", "Prussia": "PRU", "Silesia": "SIL",
    "Munich": "MUN", "Ruhr": "RUH", "Holland": "HOL", "Belgium": "BEL", "Picardy": "PIC",
    "Brest": "BRE", "Paris": "PAR", "Burgundy": "BUR", "Marseilles": "MAR", "Gascony": "GAS",
    "Barents Sea": "BAR", "Norwegian Sea": "NWG", "North Sea": "NTH", "Skagerrack": "SKA",
    "Heligoland Bight": "HEL", "Baltic Sea": "BAL", "Gulf of Bothnia": "BOT",
    "North Atlantic Ocean": "NAO", "Irish Sea": "IRI", "English Channel": "ENG",
    "Mid-Atlantic Ocean": "MAO", "Western Mediterranean": "WES", "Gulf of Lyons": "LYO",
    "Tyrrhenian Sea": "TYS", "Ionian Sea": "ION", "Adriatic Sea": "ADR", "Aegean Sea": "AEG",
    "Eastern Mediterranean": "EAS", "Black Sea": "BLA", "Tyrolia": "TYR", "Bohemia": "BOH",
    "Vienna": "VIE", "Trieste": "TRI", "Budapest": "BUD", "Galicia": "GAL",
    "Spain (North Coast)": "SPA/NC", "Spain (South Coast)": "SPA/SC",
    "St. Petersburg (North Coast)": "STP/NC", "St. Petersburg (South Coast)": "STP/SC",
    "Bulgaria (North Coast)": "BUL/EC", "Bulgaria (South Coast)": "BUL/SC",
}


class DipMap:
    def __init__(self, territories):
        self.loc = {t["id"]: ABBREVIATION[t["name"]] for t in territories}
        self.terr = {v: k for k, v in self.loc.items()}

    def unit(self, unit):
        return f'{"A" if unit["type"] == "Army" else "F"} {self.loc[unit["terrID"]]}'

    def order(self, o, unit_at):
        """webDip movement order dict -> standard notation. `unit_at`: province terrID -> unit."""
        u = unit_at[o["terrID"]]
        me = self.unit(u)
        kind = o["type"]
        if kind == "Hold":
            return f"{me} H"
        if kind == "Move":
            return f"{me} - {self.loc[o['toTerrID']]}" + (" VIA" if o.get("viaConvoy") in ("Yes", True) else "")
        if kind == "Support hold":
            return f"{me} S {self.unit(unit_at[o['toTerrID']])}"
        if kind == "Support move":
            src = unit_at[o["fromTerrID"]]
            return f"{me} S {self.unit(src)} - {self.loc[o['toTerrID']][:3]}"
        if kind == "Convoy":
            src = unit_at[o["fromTerrID"]]
            return f"{me} C {self.unit(src)} - {self.loc[o['toTerrID']][:3]}"
        raise ValueError(kind)

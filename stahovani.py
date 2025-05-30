import datetime
import pandas as pd
from typing import Any
import requests
import shelve
import time

# Nastavení počátečního a koncového datumu v časové zóně UTC
from_dt = datetime.datetime(2023, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
to_dt = datetime.datetime(2025, 5, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

# Definice kroku pro rozdělení časového období – denní interval
step = datetime.timedelta(days=1)

# Limity pro API požadavky a intervaly mezi nimi
max_requests = 19
max_interval_s = 8

# Token pro autentifikaci vůči API Golemio
token_milos = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MzQ5OSwiaWF0IjoxNzQ0Mzk3MjI1LCJleHAiOjExNzQ0Mzk3MjI1LCJpc3MiOiJnb2xlbWlvIiwianRpIjoiMTEyZDBhMDAtZGU3Zi00NzNhLWExZDUtZDllYjFlZmYyNDRmIn0.D27Uk4Gfm-SQWr-mrpeYpcKVHXA1sT_Nxt62_gY2RSo"
url = "https://api.golemio.cz"
headers = {"X-Access-Token": token_milos}

# Funkce generující seznam časových rozsahů od do
def generate_from_to_datetimes(from_dt: datetime.datetime, to_dt:  datetime.datetime, step: datetime.timedelta) -> list[dict[str, str]]:
    fn = from_dt
    l = []
    while fn <= to_dt:
        # Přidání aktuálního intervalu do seznamu
        l.append(
            {
                "from": fn.strftime("%Y-%m-%dT%H:%M:%SZ"),             # Čas začátku intervalu
                "to": (fn + step).strftime("%Y-%m-%dT%H:%M:%SZ")       # Čas konce intervalu
            }
        )
        fn += step  # Posun na další interval
    return l

# Funkce pro získání detekcí pro konkrétní cameo ID
def get_cointer_for_id(cameo: str):
    # Otevření cache pro ukládání odpovědí a minimalizaci API požadavků
    cache = shelve.open(".cache.db")
    endpoint = "/v2/bicyclecounters/detections"
    full_url = f"{url}{endpoint}"
    print(f"Fetcing cameo: {cameo}")
    responses = []

    # Inicializace časového sledování a limitů požadavků
    last_start = datetime.datetime.now()
    nrequests = max_requests
    tlimit = datetime.timedelta(seconds=max_interval_s)

    # Pro každý časový interval
    for json_data in generate_from_to_datetimes(from_dt, to_dt, step):
        json_data["id"] = cameo           # Přidání ID do parametrů
        json_data["aggregate"] = "true"   # Zapnutí agregace

        # Klíč do cache založený na parametrech požadavku
        cache_key = ";".join(json_data.values())

        # Pokud je dotaz v cache, použije uloženou odpověď
        if cache_key in cache:
            response_json = cache[cache_key]
        else:
            # Kontrola a dodržení limitu požadavků
            tdelta = datetime.datetime.now() - last_start
            if nrequests <= 0:
                nrequests = max_requests
                # Pokud je od posledního požadavku uplynul dostatečný čas, počkáme
                if tdelta.total_seconds() > 0:
                    time.sleep(tdelta.total_seconds() + 2)
                last_start = datetime.datetime.now()
            
            print(nrequests, datetime.datetime.now(), json_data)
            retry = 5  # počet pokusů při chybě
            while retry >= 0:
                response = requests.request("GET", full_url, headers=headers, params=json_data)
                nrequests -= 1
                if response.status_code == 429:
                    # Přetížení API, čekáme a opakujeme
                    print("Malo jsem cekal")
                    time.sleep(2)
                    retry -= 1
                elif response.status_code != 200:
                    # Pokud se nepodařilo získat data (stav jiný než 200 OK), snížíme počet pokusů
                    print(f"Nebyl 200, ale {response.status_code}")
                    retry -= 1
                    continue

                # Pokud je odpověď v pořádku, načteme JSON data
                response_json = response.json()
                # Uložíme odpověď do cache, abychom nemuseli opakovat požadavek
                cache[cache_key] = response_json
                break  # Při úspěchu ukončíme smyčku opakovaných pokusů

        responses.append(response_json)  # Přidáme odpověď do seznamu

    # Vytvoříme DataFrame z odpovědí, vybíráme první položku z každé odpovědi
    df = pd.DataFrame(x[0] for x in responses if len(x))
    # Přidáme sloupec 'cameo' s ID odkazu
    df["cameo"] = cameo
    cache.close()  # Zavřeme cache
    return df  # Vracíme DataFrame s daty detekcí


# Funkce převádějící geo-objekt do řádku DataFrame
def _feature_row_to_pd_row(api_data: dict) -> dict[str, Any]:
    tmp_dict = {}
    # Pro každý směr odkud kam (directions) v geometrii
    for iid, direction in enumerate(api_data["properties"]["directions"]):
        # Vytváříme dynamické kolony s indexem směru
        dd = {f"{x}_{iid}": z for x, z in direction.items()}
        tmp_dict |= dd  # Sloučíme do tmp_dict

    # Vrací slovník s informacemi o body a směrech
    return {
        "cameo_id": api_data["properties"]["id"],
        "cameo_name": api_data["properties"]["name"],
        "route": api_data["properties"]["route"],
        "updated_at": api_data["properties"]["updated_at"],
    } | dict(zip(("x", "y"), api_data["geometry"]["coordinates"])) | tmp_dict
    # Sloučí data o identifikátoru, názvu, trase, časové známce a souřadnicích


# Funkce pro získání všech bodů (cameo) - cyklistických měřičů
def get_points() -> list[str]:
    endpoint = "/v2/bicyclecounters"
    full_url = f"{url}{endpoint}"
    print(f"getting points for {full_url}")
    response = requests.request("GET", full_url, headers=headers)
    # Extrahujeme všechny směry z jednotlivých feature
    all_directions = [x["properties"]["directions"] for x in response.json()["features"]]
    cameos = set()
    for direction in all_directions:
        for x in direction:
            cameos.add(x["id"])  # Přidáme ID do množiny

    # Uložíme všechny informace do CSV
    df_data = [_feature_row_to_pd_row(x) for x in response.json()["features"]]
    pd.DataFrame(df_data).to_csv("cameos.csv", index=False)
    return list(x for x in cameos if x is not None)  # Vracej seznam IDs

# Hlavní část programu
if __name__ == "__main__":
    # Získáme všechny pointy (camaos) a pro každý stáhneme detekce
    df = pd.concat(get_cointer_for_id(cameo) for cameo in get_points())
    print(f"exporting to csv")
    # Výstupní CSV obsahující všechny detekce
    df.to_csv("points2.csv", index=False)
import datetime
import pandas as pd
from typing import Any
import requests
import shelve
import time

from_dt = datetime.datetime(2023,1,1,0,0,0, tzinfo=datetime.UTC)
to_dt = datetime.datetime(2025,5,1,0,0,0, tzinfo=datetime.UTC)
step = datetime.timedelta(days=1)
max_requests = 19
max_interval_s = 8



token_milos = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MzQ5OSwiaWF0IjoxNzQ0Mzk3MjI1LCJleHAiOjExNzQ0Mzk3MjI1LCJpc3MiOiJnb2xlbWlvIiwianRpIjoiMTEyZDBhMDAtZGU3Zi00NzNhLWExZDUtZDllYjFlZmYyNDRmIn0.D27Uk4Gfm-SQWr-mrpeYpcKVHXA1sT_Nxt62_gY2RSo"
url = "https://api.golemio.cz"
headers = {"X-Access-Token": token_milos}


def generate_from_to_datetimes(from_dt: datetime.datetime, to_dt:  datetime.datetime, step: datetime.timedelta) -> list[dict[str, str]]:
    fn = from_dt
    l = []
    while fn <= to_dt:
        l.append(
            {
                "from": fn.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": (fn+step).strftime("%Y-%m-%dT%H:%M:%SZ")
            }
        )
        fn += step
    return l




def get_cointer_for_id(cameo: str):
    cache = shelve.open(".cache.db")
    endpoint = "/v2/bicyclecounters/detections"
    full_url = f"{url}{endpoint}"
    print(f"Fetcing cameo: {cameo}")
    responses = []
    last_start, nrequests, tlimit = datetime.datetime.now(), max_requests, datetime.timedelta(seconds=max_interval_s)

    for json_data in generate_from_to_datetimes(from_dt, to_dt, step):
        json_data["id"] = cameo
        json_data["aggregate"] = "true"
        cache_key = ";".join(json_data.values())

        if cache_key in cache:
            response_json = cache[cache_key]
        else:
            tdelta = datetime.datetime.now() - last_start
            if nrequests <= 0:
                nrequests = max_requests
                if tdelta.total_seconds() > 0:
                    time.sleep(tdelta.total_seconds()+2)                
                last_start = datetime.datetime.now()

            print(nrequests, datetime.datetime.now(), json_data)
            retry = 5
            while retry >= 0:
                response = requests.request("GET", full_url, headers=headers, params=json_data) 
                nrequests -= 1
                if response.status_code == 429:
                    print("Malo jsem cekal")
                    time.sleep(2)
                    retry -= 1
                    continue
                elif response.status_code != 200:
                    print(f"Nebyl 200, ale {response.status_code}")
                    retry -= 1
                    continue
                
                response_json = response.json()
                cache[cache_key] = response_json
                break
            

        responses.append(response_json)
        
    df = pd.DataFrame(x[0] for x in responses if len(x))
    df["cameo"] = cameo
    cache.close()
    return df


def _feature_row_to_pd_row(api_data: dict) -> dict[str, Any]:
    tmp_dict = {}
    for iid, direction in enumerate(api_data["properties"]["directions"]):
        dd = {f"{x}_{iid}":z for x,z in direction.items()}
        tmp_dict |= dd

    return {
        "cameo_id": api_data["properties"]["id"],
        "cameo_name": api_data["properties"]["name"],
        "route": api_data["properties"]["route"],
        "updated_at": api_data["properties"]["updated_at"],
    } | dict(zip( ("x", "y"), api_data["geometry"]["coordinates"])) | tmp_dict


def get_points() -> list[str]:
    endpoint = "/v2/bicyclecounters"
    full_url = f"{url}{endpoint}"
    print(f"getting points for {full_url}")
    response = requests.request("GET", full_url, headers=headers)
    # Extract ID for directions
    all_directions = [x["properties"]["directions"] for x in response.json()["features"]]
    cameos = set()
    for direction in all_directions:
        for x in direction:
            cameos.add(x["id"])
    # Persist all came information
    df_data = [_feature_row_to_pd_row(x) for x in response.json()["features"]]
    pd.DataFrame(df_data).to_csv("cameos.csv", index=False)
    return list(x for x in cameos if x is not None)



if __name__ == "__main__":
    df = pd.concat(get_cointer_for_id(cameo) for cameo in get_points())
    print(f"exporting to csv")
    df.to_csv("points2.csv", index=False) 